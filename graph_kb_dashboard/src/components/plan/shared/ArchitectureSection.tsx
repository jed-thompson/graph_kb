'use client';

import type { LucideIcon } from 'lucide-react';
import { ArchitectureFeedbackItem, type ItemFeedback } from './ArchitectureFeedbackItem';

interface ArchitectureSectionProps {
    title: string;
    icon: LucideIcon;
    items: string[];
    sectionKey: string;
    feedback: Record<string, ItemFeedback>;
    onChange: (sectionKey: string, itemFeedback: Record<string, ItemFeedback>) => void;
    /** @deprecated Badge variant no longer used — items render as list rows */
    badgeVariant?: 'secondary' | 'outline';
}

export function ArchitectureSection({
    title,
    icon: Icon,
    items,
    sectionKey,
    feedback,
    onChange,
}: ArchitectureSectionProps) {
    if (items.length === 0) return null;

    const handleItemChange = (itemId: string, fb: ItemFeedback) => {
        onChange(sectionKey, { ...feedback, [itemId]: fb });
    };

    return (
        <div>
            {title && (
                <div className="flex items-center gap-2 mb-2">
                    <Icon className="h-4 w-4 text-muted-foreground" />
                    <h4 className="font-medium text-sm">{title}</h4>
                </div>
            )}
            <div className="space-y-1.5">
                {items.map((item) => (
                    <ArchitectureFeedbackItem
                        key={item}
                        itemId={item}
                        label={item}
                        value={feedback[item]}
                        onChange={handleItemChange}
                    />
                ))}
            </div>
        </div>
    );
}
