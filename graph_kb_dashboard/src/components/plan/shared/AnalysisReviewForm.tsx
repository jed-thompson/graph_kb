'use client';

import { useState } from 'react';
import { CardFooter } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { CollapsibleCard } from '@/components/ui/CollapsibleCard';
import {
    CheckCircle,
    AlertCircle,
    Lightbulb,
    HelpCircle,
    MessageSquare,
    AlertTriangle,
    Info,
    Loader2,
    Monitor,
    Blocks,
    Link,
    Package,
    BookOpen,
    Server,
} from 'lucide-react';
import type { PlanPhaseId } from '@/lib/store/planStore';
import { cleanAIText } from '@/lib/utils/cleanAIText';
import { ArchitectureSection } from './ArchitectureSection';
import { ArchitectureFeedbackItem, type ItemFeedback } from './ArchitectureFeedbackItem';
export type { ContextItems } from './ContextItemsPanel';

// Types
export interface Gap {
    id: string;
    category: string;
    title: string;
    description: string;
    severity: 'high' | 'medium' | 'low';
}

export interface ClarificationQuestion {
    id: string;
    question: string;
    context?: string;
    suggestedAnswers?: string[];
}

export interface ArchitectureAnalysis {
    implications: {
        systemsToModify: string[];
        newComponentsNeeded: string[];
        integrationPoints: string[];
    };
    riskAreas: Array<{
        category: string;
        description: string;
        severity: string;
        mitigation?: string;
    }>;
    dependencies: {
        externalSystems: string[];
        libraries: string[];
        services: string[];
    };
}

export interface AnalysisReviewFormProps {
    phase: PlanPhaseId;
    completenessScore: number;
    gaps?: Gap[];
    clarificationQuestions?: ClarificationQuestion[];
    suggestedActions?: string[];
    architectureAnalysis?: ArchitectureAnalysis;
    onSubmit: (data: AnalysisReviewFormData) => void;
}

export interface AnalysisReviewFormData {
    [key: string]: unknown;
    answers: Record<string, string>;
    additional_context: string;
    acknowledged: boolean;
    architecture_feedback?: Record<string, Record<string, ItemFeedback>>;
}

/** Normalize architecture_analysis — handles both snake_case (backend) and camelCase keys. */
function normalizeArchitectureAnalysis(
    raw: ArchitectureAnalysis | Record<string, unknown> | undefined,
): ArchitectureAnalysis | undefined {
    if (!raw) return undefined;

    const r = raw as Record<string, unknown>;
    const impl = (r.implications ?? {}) as Record<string, unknown>;
    const deps = (r.dependencies ?? {}) as Record<string, unknown>;

    return {
        implications: {
            systemsToModify: (impl.systemsToModify ?? impl.systems_to_modify ?? []) as string[],
            newComponentsNeeded: (impl.newComponentsNeeded ?? impl.new_components_needed ?? []) as string[],
            integrationPoints: (impl.integrationPoints ?? impl.integration_points ?? []) as string[],
        },
        riskAreas: (r.riskAreas ?? r.risk_areas ?? []) as ArchitectureAnalysis['riskAreas'],
        dependencies: {
            externalSystems: (deps.externalSystems ?? deps.external_systems ?? []) as string[],
            libraries: (deps.libraries ?? []) as string[],
            services: (deps.services ?? []) as string[],
        },
    };
}

export function AnalysisReviewForm({
    phase: _phase,
    completenessScore = 0,
    gaps = [],
    clarificationQuestions = [],
    suggestedActions = [],
    architectureAnalysis: rawArchitectureAnalysis,
    onSubmit,
}: AnalysisReviewFormProps) {
    // Defense-in-depth: gaps should already be normalized by BasePhaseContent, but guard here too
    const safeGaps = Array.isArray(gaps)
        ? gaps
        : gaps && typeof gaps === 'object'
            ? Object.values(gaps) as unknown as Gap[]
            : [];

    // Normalize architecture_analysis — backend may send snake_case keys
    const architectureAnalysis = normalizeArchitectureAnalysis(rawArchitectureAnalysis as ArchitectureAnalysis | Record<string, unknown> | undefined);

    const [answers, setAnswers] = useState<Record<string, string>>({});
    const [additionalContext, setAdditionalContext] = useState('');
    const [acknowledged, setAcknowledged] = useState(false);
    const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
    const [architectureFeedback, setArchitectureFeedback] = useState<Record<string, Record<string, ItemFeedback>>>({});

    // Handle answer changes
    const handleAnswerChange = (questionId: string, answer: string) => {
        setAnswers((prev) => ({ ...prev, [questionId]: answer }));
    };

    const handleSubmit = () => {
        const unanswered = clarificationQuestions.filter(
            (q) => !answers[q.id]
        );
        if (unanswered.length > 0) {
            console.warn(`${unanswered.length} unanswered questions`);
        }

        setIsSubmitting(true);
        onSubmit({
            answers,
            additional_context: additionalContext,
            acknowledged,
            architecture_feedback: architectureFeedback,
        });
    };

    // Helper functions
    const getSeverityColor = (severity: string) => {
        switch (severity) {
            case 'high':
                return 'destructive' as const;
            case 'medium':
                return 'default' as const;
            case 'low':
                return 'secondary' as const;
            default:
                return 'outline' as const;
        }
    };

    const getSeverityIcon = (severity: string) => {
        switch (severity) {
            case 'high':
                return <AlertTriangle className="h-4 w-4" />;
            case 'medium':
                return <AlertCircle className="h-4 w-4" />;
            case 'low':
                return <Info className="h-4 w-4" />;
            default:
                return null;
        }
    };

    const getCompletenessColor = (score: number) => {
        if (score >= 0.8) return 'default' as const;
        if (score >= 0.6) return 'secondary' as const;
        if (score >= 0.4) return 'outline' as const;
        return 'destructive' as const;
    };

    const getCompletenessLabel = (score: number) => {
        if (score >= 0.8) return 'Excellent';
        if (score >= 0.6) return 'Good';
        if (score >= 0.4) return 'Needs Work';
        return 'Incomplete';
    };

    return (
        <div className="space-y-6">
            {/* Header */}
            <div className="flex items-center gap-3">
                <div className="flex items-center justify-center h-10 w-10 rounded-full bg-blue-100 dark:bg-blue-900/30">
                    <CheckCircle className="h-5 w-5 text-blue-600 dark:text-blue-400" />
                </div>
                <div>
                    <h2 className="text-xl font-semibold">Context Analysis Review</h2>
                    <p className="text-sm text-muted-foreground">
                        Review the AI analysis and provide clarifications
                    </p>
                </div>
            </div>

            {/* Completeness Score */}
            <div className="flex items-center gap-4">
                <span className="text-sm font-medium">Completeness:</span>
                <Progress value={completenessScore * 100} className="flex-1 h-3" />
                <Badge variant={getCompletenessColor(completenessScore)}>
                    {getCompletenessLabel(completenessScore)}
                </Badge>
            </div>

            {/* Gaps Detected */}
            {safeGaps && safeGaps.length > 0 && (
                <CollapsibleCard
                    title="Gaps Detected"
                    icon={<AlertTriangle className="h-4 w-4" />}
                    badge={<Badge variant="destructive">{safeGaps.length}</Badge>}
                    defaultExpanded={true}
                    variant="warning"
                    size="sm"
                >
                    <div className="space-y-4">
                        {safeGaps.map((gap) => (
                            <div key={gap.id} className="flex items-start gap-2">
                                <Badge variant={getSeverityColor(gap.severity)} className="mt-0.5">
                                    {getSeverityIcon(gap.severity)}
                                    <span className="sr-only">{gap.severity}</span>
                                </Badge>
                                <div className="flex-1 min-w-0">
                                    <h4 className="font-medium text-sm">{cleanAIText(gap.title)}</h4>
                                    <p className="text-xs text-muted-foreground mt-1">{cleanAIText(gap.description)}</p>
                                </div>
                            </div>
                        ))}
                    </div>
                </CollapsibleCard>
            )}

            {/* Clarification Questions */}
            {clarificationQuestions && clarificationQuestions.length > 0 && (
                <CollapsibleCard
                    title="Clarification Questions"
                    icon={<HelpCircle className="h-4 w-4" />}
                    badge={<Badge variant="secondary">{clarificationQuestions.length}</Badge>}
                    defaultExpanded={true}
                    size="sm"
                >
                    <div className="space-y-4">
                        {clarificationQuestions.map((q) => (
                            <div key={q.id} className="border-l-2 border-primary/20 pl-4 py-1">
                                <div className="flex items-start gap-2 mb-2">
                                    <MessageSquare className="h-4 w-4 text-muted-foreground mt-0.5" />
                                    <span className="font-medium text-sm flex-1">{cleanAIText(q.question)}</span>
                                </div>
                                <div>
                                    <Textarea
                                        placeholder="Your answer..."
                                        value={answers[q.id] || ''}
                                        onChange={(e) => handleAnswerChange(q.id, e.target.value)}
                                        className="min-h-[60px] resize-y text-sm"
                                    />
                                    {q.suggestedAnswers && q.suggestedAnswers.length > 0 && (
                                        <div className="mt-2">
                                            <p className="text-xs text-muted-foreground">
                                                Suggested: {q.suggestedAnswers.join(', ')}
                                            </p>
                                        </div>
                                    )}
                                </div>
                            </div>
                        ))}
                    </div>
                </CollapsibleCard>
            )}

            {/* Suggested Actions */}
            {suggestedActions && suggestedActions.length > 0 && (
                <CollapsibleCard
                    title="Suggested Actions"
                    icon={<Lightbulb className="h-4 w-4" />}
                    badge={<Badge variant="outline">{suggestedActions.length}</Badge>}
                    defaultExpanded={true}
                    size="sm"
                >
                    <ul className="space-y-2">
                        {suggestedActions.map((action, idx) => (
                            <li key={idx} className="flex items-start gap-2 text-sm">
                                <CheckCircle className="h-4 w-4 text-primary mt-0.5" />
                                <span className="flex-1">{action}</span>
                            </li>
                        ))}
                    </ul>
                </CollapsibleCard>
            )}

            {/* Architecture Analysis */}
            {architectureAnalysis && Object.keys(architectureAnalysis).length > 0 && (
                <CollapsibleCard
                    title="Technical Analysis"
                    icon={<Blocks className="h-4 w-4" />}
                    badge={<Badge variant="outline">{architectureAnalysis.riskAreas?.length || 0} Risks</Badge>}
                    defaultExpanded={true}
                    size="sm"
                >
                    <div className="space-y-4">
                        <CollapsibleCard
                            title="Systems to Modify"
                            icon={<Monitor className="h-4 w-4" />}
                            defaultExpanded={true}
                            size="sm"
                        >
                            <ArchitectureSection
                                items={architectureAnalysis.implications?.systemsToModify ?? []}
                                sectionKey="systems_to_modify"
                                feedback={architectureFeedback.systems_to_modify ?? {}}
                                onChange={(key, fb) => setArchitectureFeedback(prev => ({ ...prev, [key]: fb }))}
                                title=""
                                icon={Monitor}
                            />
                        </CollapsibleCard>

                        <CollapsibleCard
                            title="New Components"
                            icon={<Blocks className="h-4 w-4" />}
                            defaultExpanded={true}
                            size="sm"
                        >
                            <ArchitectureSection
                                items={architectureAnalysis.implications?.newComponentsNeeded ?? []}
                                sectionKey="new_components"
                                feedback={architectureFeedback.new_components ?? {}}
                                onChange={(key, fb) => setArchitectureFeedback(prev => ({ ...prev, [key]: fb }))}
                                title=""
                                icon={Blocks}
                                badgeVariant="outline"
                            />
                        </CollapsibleCard>

                        <CollapsibleCard
                            title="Integration Points"
                            icon={<Link className="h-4 w-4" />}
                            defaultExpanded={true}
                            size="sm"
                        >
                            <ArchitectureSection
                                items={architectureAnalysis.implications?.integrationPoints ?? []}
                                sectionKey="integration_points"
                                feedback={architectureFeedback.integration_points ?? {}}
                                onChange={(key, fb) => setArchitectureFeedback(prev => ({ ...prev, [key]: fb }))}
                                title=""
                                icon={Link}
                            />
                        </CollapsibleCard>

                        {/* Risk Areas */}
                        {architectureAnalysis.riskAreas?.length > 0 && (
                            <CollapsibleCard
                                title="Risks"
                                icon={<AlertTriangle className="h-4 w-4" />}
                                badge={<Badge variant="destructive">{architectureAnalysis.riskAreas.length}</Badge>}
                                defaultExpanded={true}
                                variant="warning"
                                size="sm"
                            >
                                <div className="space-y-1.5">
                                    {architectureAnalysis.riskAreas.map((risk, idx) => (
                                        <ArchitectureFeedbackItem
                                            key={`${risk.category}-${idx}`}
                                            itemId={`${risk.category}-${idx}`}
                                            label={risk.category}
                                            description={cleanAIText([risk.description, risk.mitigation ? `Mitigation: ${risk.mitigation}` : ''].filter(Boolean).join('. '))}
                                            value={architectureFeedback.risks?.[`${risk.category}-${idx}`]}
                                            onChange={(_id: string, fb: ItemFeedback) => setArchitectureFeedback(prev => ({
                                                ...prev,
                                                risks: { ...(prev.risks ?? {}), [`${risk.category}-${idx}`]: fb },
                                            }))}
                                        >
                                            <div className="flex items-center gap-2">
                                                {getSeverityIcon(risk.severity)}
                                                <span className="text-sm font-medium">{risk.category}</span>
                                                <Badge variant={getSeverityColor(risk.severity)} className="text-[10px] uppercase h-4 px-1">
                                                    {risk.severity}
                                                </Badge>
                                            </div>
                                        </ArchitectureFeedbackItem>
                                    ))}
                                </div>
                            </CollapsibleCard>
                        )}

                        {/* Dependencies */}
                        {(architectureAnalysis.dependencies?.externalSystems?.length > 0 ||
                          architectureAnalysis.dependencies?.libraries?.length > 0 ||
                          architectureAnalysis.dependencies?.services?.length > 0) && (
                            <CollapsibleCard
                                title="Dependencies"
                                icon={<Package className="h-4 w-4" />}
                                defaultExpanded={true}
                                size="sm"
                            >
                                <div className="space-y-4">
                                    <ArchitectureSection
                                        title="External Systems"
                                        icon={Server}
                                        items={architectureAnalysis.dependencies.externalSystems ?? []}
                                        sectionKey="external_systems"
                                        feedback={architectureFeedback.external_systems ?? {}}
                                        onChange={(key, fb) => setArchitectureFeedback(prev => ({ ...prev, [key]: fb }))}
                                    />
                                    <ArchitectureSection
                                        title="Libraries"
                                        icon={BookOpen}
                                        items={architectureAnalysis.dependencies.libraries ?? []}
                                        sectionKey="libraries"
                                        feedback={architectureFeedback.libraries ?? {}}
                                        onChange={(key, fb) => setArchitectureFeedback(prev => ({ ...prev, [key]: fb }))}
                                        badgeVariant="outline"
                                    />
                                    <ArchitectureSection
                                        title="Services"
                                        icon={Link}
                                        items={architectureAnalysis.dependencies.services ?? []}
                                        sectionKey="services"
                                        feedback={architectureFeedback.services ?? {}}
                                        onChange={(key, fb) => setArchitectureFeedback(prev => ({ ...prev, [key]: fb }))}
                                    />
                                </div>
                            </CollapsibleCard>
                        )}
                    </div>
                </CollapsibleCard>
            )}

            {/* Additional Context */}
            <div className="space-y-3">
                <label className="text-sm font-medium">
                    Optional: Add any additional context or clarifications
                </label>
                <Textarea
                    placeholder="Any additional context, clarifications, or insights that should be considered..."
                    value={additionalContext}
                    onChange={(e) => setAdditionalContext(e.target.value)}
                    className="min-h-[80px] text-sm"
                />
            </div>

            {/* Action Buttons */}
            <CardFooter className="flex justify-between gap-3 px-0 pt-4 border-t">
                <Button
                    variant="ghost"
                    onClick={() => {
                        setAcknowledged(true);
                        handleSubmit();
                    }}
                    disabled={isSubmitting}
                    className="flex-1"
                >
                    <HelpCircle className="h-4 w-4 mr-2" />
                    Acknowledge All & Proceed
                </Button>
                <Button onClick={handleSubmit} disabled={isSubmitting} className="flex-1">
                    {isSubmitting ? (
                        <>
                            <Loader2 className="h-4 w-4 animate-spin mr-2" />
                            Submitting...
                        </>
                    ) : (
                        <>
                            <CheckCircle className="h-4 w-4 mr-2" />
                            Submit Review
                        </>
                    )}
                </Button>
            </CardFooter>
        </div>
    );
}
