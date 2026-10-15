import { createFileRoute } from '@tanstack/react-router';
import { ComplaintsPage } from '@/components/civic/CitizenPages';
import { complaintsQuery } from '@/components/civic/shared';
import { civicHead } from '@/lib/civic-head';
export const Route = createFileRoute('/complaints/')({ head: () => civicHead('My complaints', 'Search and follow your municipal grievance reports and accountable departments.'), loader: async ({ context }) => { await context.queryClient.ensureQueryData(complaintsQuery); }, component: ComplaintsPage });
