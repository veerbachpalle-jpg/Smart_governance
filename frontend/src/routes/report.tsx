import { createFileRoute } from '@tanstack/react-router';
import { SubmitPage } from '@/components/civic/CitizenPages';
import { complaintsQuery } from '@/components/civic/shared';
import { civicHead } from '@/lib/civic-head';
export const Route = createFileRoute('/report')({ validateSearch: (s: Record<string, unknown>): { category?: string } => (typeof s['category'] === 'string' ? { category: s['category'] } : {}), head: () => civicHead('Submit a complaint', 'Report a municipal issue with a location and supporting evidence through CivicSense.'), loader: async ({ context }) => { await context.queryClient.ensureQueryData(complaintsQuery); }, component: Page });
function Page() { const { category } = Route.useSearch(); return <SubmitPage {...(category ? { initialCategory: category } : {})}/>; }
