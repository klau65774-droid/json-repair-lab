import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { API_CONTRACT, MODEL_CONTRACT } from '../contract';

type JsonObject = Record<string, unknown>;

const openApi = JSON.parse(
  readFileSync(resolve(process.cwd(), '../后端/docs/openapi.json'), 'utf8'),
) as {
  paths: Record<string, Record<string, JsonObject>>;
  components: { schemas: Record<string, JsonObject> };
};

function schemaRef(schema: JsonObject | undefined): string | null {
  const ref = schema?.$ref;
  return typeof ref === 'string' ? ref.replace('#/components/schemas/', '') : null;
}

function collectRefs(value: unknown, refs = new Set<string>()): Set<string> {
  if (Array.isArray(value)) {
    value.forEach((item) => collectRefs(item, refs));
  } else if (value && typeof value === 'object') {
    const record = value as JsonObject;
    if (typeof record.$ref === 'string') {
      refs.add(record.$ref.replace('#/components/schemas/', ''));
    }
    Object.values(record).forEach((item) => collectRefs(item, refs));
  }
  return refs;
}

function collectEnums(schema: JsonObject): string[] {
  const values = new Set<string>();
  const visit = (value: unknown) => {
    if (Array.isArray(value)) {
      value.forEach(visit);
      return;
    }
    if (!value || typeof value !== 'object') return;
    const record = value as JsonObject;
    if (typeof record.const === 'string') values.add(record.const);
    if (Array.isArray(record.enum)) {
      record.enum.forEach((item) => {
        if (typeof item === 'string') values.add(item);
      });
    }
    Object.entries(record).forEach(([key, child]) => {
      if (key !== 'enum' && key !== 'const') visit(child);
    });
  };
  visit(schema);
  return [...values].sort();
}

describe('backend OpenAPI contract', () => {
  it('covers exactly the eight laboratory routes and methods', () => {
    const expected = [
      'GET /api/health',
      'GET /api/presets',
      'POST /api/repair',
      'POST /api/stream/simulate',
      'POST /api/stream/sse',
      'POST /api/schema/validate',
      'POST /api/benchmarks/run',
      'POST /api/dos/audit',
    ].sort();
    const covered = API_CONTRACT.map((route) => `${route.method} ${route.path}`).sort();
    const published = Object.entries(openApi.paths).flatMap(([path, operations]) =>
      Object.keys(operations).map((method) => `${method.toUpperCase()} ${path}`),
    ).sort();

    expect(covered).toEqual(expected);
    expect(published).toEqual(expected);
  });

  it('matches request bodies and success response schemas', () => {
    for (const route of API_CONTRACT) {
      const operation = openApi.paths[route.path]?.[route.method.toLowerCase()];
      expect(operation, `${route.method} ${route.path}`).toBeDefined();

      const requestSchema = (operation?.requestBody as JsonObject | undefined)
        ?.content as JsonObject | undefined;
      const requestJson = requestSchema?.['application/json'] as JsonObject | undefined;
      const actualRequest = schemaRef(requestJson?.schema as JsonObject | undefined);
      expect(actualRequest, `${route.path} request`).toBe('request' in route ? route.request : null);

      const responses = operation?.responses as JsonObject;
      const success = responses['200'] as JsonObject;
      const content = success.content as JsonObject;
      if (route.response === 'SSE string') {
        const eventStream = content['text/event-stream'] as JsonObject;
        expect((eventStream.schema as JsonObject).type).toBe('string');
      } else {
        const json = content['application/json'] as JsonObject;
        const schema = json.schema as JsonObject;
        if (route.response.endsWith('[]')) {
          expect(schema.type).toBe('array');
          expect(schemaRef(schema.items as JsonObject)).toBe(route.response.slice(0, -2));
        } else {
          expect(schemaRef(schema)).toBe(route.response);
        }
      }
    }
  });

  it('matches every reachable model field, required set, and enum', () => {
    const reachable = new Set<string>();
    for (const route of API_CONTRACT) {
      const operation = openApi.paths[route.path][route.method.toLowerCase()];
      collectRefs(operation.requestBody, reachable);
      collectRefs(operation.responses, reachable);
    }
    const pending = [...reachable];
    for (let index = 0; index < pending.length; index += 1) {
      const before = new Set(reachable);
      collectRefs(openApi.components.schemas[pending[index]], reachable);
      reachable.forEach((name) => {
        if (!before.has(name)) pending.push(name);
      });
    }

    expect([...reachable].sort()).toEqual(Object.keys(MODEL_CONTRACT).sort());

    for (const modelName of reachable) {
      const schema = openApi.components.schemas[modelName];
      const contract = MODEL_CONTRACT[modelName];
      expect(contract, `${modelName} frontend model`).toBeDefined();
      const properties = (schema.properties ?? {}) as Record<string, JsonObject>;
      const required = (schema.required ?? []) as string[];
      const declaredFields = [...contract.required, ...contract.optional].sort();

      expect(Object.keys(properties).sort(), `${modelName} fields`).toEqual(declaredFields);
      expect([...required].sort(), `${modelName} required`).toEqual([...contract.required].sort());

      for (const [field, fieldSchema] of Object.entries(properties)) {
        expect(collectEnums(fieldSchema), `${modelName}.${field} enum`).toEqual(
          [...(contract.enums[field] ?? [])].sort(),
        );
      }
    }
  });
});
