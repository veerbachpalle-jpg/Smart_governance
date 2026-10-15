import { createFileRoute } from '@tanstack/react-router';
import { StaffPage } from '@/components/civic/StaffPages';
import { complaintsQuery } from '@/components/civic/shared';
import { civicHead } from '@/lib/civic-head';
export const Route = createFileRoute('/staff/$view')({ head: ({params}) => civicHead(`Staff ${params.view}`, 'Human-led municipal operations, triage, independent review and accountable civic services.'), loader: async ({ context }) => { await context.queryClient.ensureQueryData(complaintsQuery); }, component: Page });
function Page() { const {view}=Route.useParams();return <StaffPage view={view}/>; }
