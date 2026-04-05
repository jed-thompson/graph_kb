'use client';

import { Badge } from '@/components/ui/badge';
import { User, GitBranch } from 'lucide-react';
import { cleanAIText } from '@/lib/utils/cleanAIText';
import type { TaskItem } from '../PlanContext';

interface TaskListRendererProps {
    tasks: TaskItem[];
}

const priorityColor: Record<string, 'destructive' | 'default' | 'secondary'> = {
    high: 'destructive',
    medium: 'default',
    low: 'secondary',
};

export function TaskListRenderer({ tasks }: TaskListRendererProps) {
    if (!tasks || tasks.length === 0) {
        return <span className="text-muted-foreground italic text-xs">No tasks</span>;
    }

    return (
        <div className="space-y-2 mt-1">
            {tasks.map((task) => (
                <div
                    key={task.id}
                    className="bg-background/80 px-3 py-2.5 rounded-md border"
                >
                    <div className="flex items-center justify-between gap-2">
                        <span className="text-xs font-medium leading-tight">
                            {cleanAIText(task.name)}
                        </span>
                        <Badge
                            variant={priorityColor[task.priority] ?? 'default'}
                            className="text-[10px] shrink-0"
                        >
                            {task.priority}
                        </Badge>
                    </div>
                    {task.description && (
                        <p className="text-xs text-muted-foreground mt-1 leading-relaxed line-clamp-2">
                            {cleanAIText(task.description)}
                        </p>
                    )}
                    <div className="flex items-center gap-3 mt-1.5 text-[11px] text-muted-foreground">
                        {task.agent_type && (
                            <span className="inline-flex items-center gap-1">
                                <User className="h-3 w-3" />
                                {task.agent_type}
                            </span>
                        )}
                        {task.dependencies.length > 0 && (
                            <span className="inline-flex items-center gap-1">
                                <GitBranch className="h-3 w-3" />
                                {task.dependencies.length} dep{task.dependencies.length > 1 ? 's' : ''}
                            </span>
                        )}
                    </div>
                </div>
            ))}
        </div>
    );
}
