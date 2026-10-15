import { createFileRoute } from '@tanstack/react-router';
import { StaffCase } from '@/components/civic/StaffPages';
import { complaintsQuery } from '@/components/civic/shared';
import { civicHead } from '@/lib/civic-head';
export const Route = createFileRoute('/staff/case/$id')({ head: ({params}) => civicHead(`Review case ${params.id}`, 'Review original reports, human triage decisions and municipal resolution evidence.'), loader: async ({ context }) => { await context.queryClient.ensureQueryData(complaintsQuery); }, component: Page });
function Page() { const {id}=Route.useParams();return <StaffCase id={id}/>; }
