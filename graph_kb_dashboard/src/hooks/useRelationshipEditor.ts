'use client';

import { useState } from 'react';
import { useResearchStore } from '@/lib/store/researchStore';
import type { RelationshipType } from '@/lib/types/research';

export function useRelationshipEditor() {
  const { relationships, addRelationship, removeRelationship } = useResearchStore();
  const [sourceId, setSourceId] = useState('');
  const [targetId, setTargetId] = useState('');
  const [relType, setRelType] = useState<RelationshipType>('dependency');

  const handleAdd = () => {
    if (!sourceId || !targetId || sourceId === targetId) return;
    addRelationship({
      id: crypto.randomUUID(),
      sourceRepoId: sourceId,
      targetRepoId: targetId,
      relationshipType: relType,
    });
    setSourceId('');
    setTargetId('');
  };

  return {
    relationships,
    removeRelationship,
    sourceId,
    setSourceId,
    targetId,
    setTargetId,
    relType,
    setRelType,
    handleAdd,
  };
}
