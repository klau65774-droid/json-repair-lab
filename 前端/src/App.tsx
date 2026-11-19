import { useState } from 'react';
import { AppHeader, type LabTab } from './components/AppHeader';
import { BenchmarksLab } from './features/benchmarks/BenchmarksLab';
import { RepairLab } from './features/repair/RepairLab';
import { StreamingLab } from './features/streaming/StreamingLab';
import { useWorkbench } from './hooks/useWorkbench';

export default function App() {
  const [activeTab, setActiveTab] = useState<LabTab>('repair');
  const workbench = useWorkbench();

  return (
    <div className="min-h-screen bg-lab-bg text-lab-text">
      <AppHeader activeTab={activeTab} onTabChange={setActiveTab} />
      <main className="p-3 xl:p-4">
        {activeTab === 'repair' && <RepairLab lab={workbench} />}
        {activeTab === 'streaming' && <StreamingLab lab={workbench} />}
        {activeTab === 'benchmarks' && <BenchmarksLab lab={workbench} />}
      </main>
    </div>
  );
}
