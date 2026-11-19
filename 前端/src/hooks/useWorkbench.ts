import { useCallback, useEffect, useMemo, useState } from 'react';
import { getPresets, repair } from '../api/client';
import type { BenchmarkResult, JsonSchema, Preset, RepairPolicy, RepairRequest, RepairResultModel } from '../api/types';

export function schemaToText(schema: JsonSchema | null | undefined): string {
  return schema === null || schema === undefined ? '' : JSON.stringify(schema, null, 2);
}

export function parseSchemaText(text: string): JsonSchema | null {
  if (!text.trim()) return null;
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    throw new Error('Schema must be valid JSON.');
  }
  if (typeof value !== 'boolean' && (value === null || Array.isArray(value) || typeof value !== 'object')) {
    throw new Error('Schema must be a JSON object or boolean.');
  }
  return value as JsonSchema;
}

export function useWorkbench() {
  const [presets, setPresets] = useState<Preset[]>([]);
  const [presetsLoading, setPresetsLoading] = useState(true);
  const [presetsError, setPresetsError] = useState<string | null>(null);
  const [selectedPresetId, setSelectedPresetId] = useState<string | null>(null);
  const [rawText, setRawText] = useState('');
  const [schemaText, setSchemaText] = useState('');
  const [policy, setPolicy] = useState<RepairPolicy>('coerce');
  const [compareBaseline, setCompareBaseline] = useState(true);
  const [cleanLlm, setCleanLlm] = useState(true);
  const [redactLogs, setRedactLogs] = useState(true);
  const [repairResult, setRepairResult] = useState<RepairResultModel | null>(null);
  const [repairLoading, setRepairLoading] = useState(false);
  const [repairError, setRepairError] = useState<string | null>(null);
  const [benchmarkResult, setBenchmarkResult] = useState<BenchmarkResult | null>(null);

  const submitRepair = useCallback(async (input: RepairRequest) => {
    setRepairLoading(true);
    setRepairError(null);
    try {
      const result = await repair(input);
      setRepairResult(result);
    } catch (error) {
      setRepairResult(null);
      setRepairError(error instanceof Error ? error.message : 'Repair request failed.');
    } finally {
      setRepairLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    setPresetsLoading(true);
    void getPresets()
      .then((items) => {
        if (!active) return;
        setPresets(items);
        setPresetsError(null);
        const first = items[0];
        if (first) {
          setSelectedPresetId(first.id);
          setRawText(first.raw_text);
          setSchemaText(schemaToText(first.json_schema));
          setPolicy(first.policy ?? 'coerce');
          void submitRepair({
            raw_text: first.raw_text,
            json_schema: first.json_schema ?? null,
            mode: 'enhanced',
            policy: first.policy ?? 'coerce',
            clean_llm: true,
            redact_logs: true,
            compare_baseline: true,
          });
        }
      })
      .catch((error: unknown) => {
        if (active) setPresetsError(error instanceof Error ? error.message : 'Could not load presets.');
      })
      .finally(() => {
        if (active) setPresetsLoading(false);
      });
    return () => {
      active = false;
    };
  }, [submitRepair]);

  const selectedPreset = useMemo(
    () => presets.find((preset) => preset.id === selectedPresetId) ?? null,
    [presets, selectedPresetId],
  );

  const applyPreset = useCallback((preset: Preset) => {
    setSelectedPresetId(preset.id);
    setRawText(preset.raw_text);
    setSchemaText(schemaToText(preset.json_schema));
    setPolicy(preset.policy ?? 'coerce');
    void submitRepair({
      raw_text: preset.raw_text,
      json_schema: preset.json_schema ?? null,
      mode: 'enhanced',
      policy: preset.policy ?? 'coerce',
      clean_llm: cleanLlm,
      redact_logs: redactLogs,
      compare_baseline: compareBaseline,
    });
  }, [cleanLlm, compareBaseline, redactLogs, submitRepair]);

  const runRepair = useCallback(async () => {
    let jsonSchema: JsonSchema | null;
    try {
      jsonSchema = parseSchemaText(schemaText);
    } catch (error) {
      setRepairError(error instanceof Error ? error.message : 'Schema must be valid JSON.');
      return;
    }
    await submitRepair({
      raw_text: rawText,
      json_schema: jsonSchema,
      mode: 'enhanced',
      policy,
      clean_llm: cleanLlm,
      redact_logs: redactLogs,
      compare_baseline: compareBaseline,
    });
  }, [cleanLlm, compareBaseline, policy, rawText, redactLogs, schemaText, submitRepair]);

  return {
    presets,
    presetsLoading,
    presetsError,
    selectedPreset,
    selectedPresetId,
    rawText,
    setRawText,
    schemaText,
    setSchemaText,
    policy,
    setPolicy,
    compareBaseline,
    setCompareBaseline,
    cleanLlm,
    setCleanLlm,
    redactLogs,
    setRedactLogs,
    repairResult,
    repairLoading,
    repairError,
    setRepairError,
    applyPreset,
    runRepair,
    benchmarkResult,
    setBenchmarkResult,
  };
}

export type Workbench = ReturnType<typeof useWorkbench>;
