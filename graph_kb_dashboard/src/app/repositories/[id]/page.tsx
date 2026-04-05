'use client';

import { useEffect, useState } from 'react';
import { RepositoryDetail } from '@/components/repository/RepositoryDetail';

export default function RepositoryDetailPage({
  params,
}: {
  params: { id: string };
}) {
  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <RepositoryDetail repoId={params.id} />
      </div>
    </div>
  );
}
