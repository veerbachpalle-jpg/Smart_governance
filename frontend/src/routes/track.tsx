import { createFileRoute } from '@tanstack/react-router';
import { TrackPage } from '@/components/civic/CitizenPages';
import { complaintsQuery } from '@/components/civic/shared';
import { civicHead } from '@/lib/civic-head';
export const Route = createFileRoute('/track')({ validateSearch: (s: Record<string, unknown>): { id?: string } => (typeof s['id'] === 'string' ? { id: s['id'] } : {}), head: () => civicHead('Track a complaint', 'Follow your CivicSense municipal report using its tracking ID.'), loader: async ({ context }) => { await context.queryClient.ensureQueryData(complaintsQuery); }, component: Page });
function Page() { const {id}=Route.useSearch();return <TrackPage {...(id ? { initialId: id } : {})}/>; }
