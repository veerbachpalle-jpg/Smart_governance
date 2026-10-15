import { createFileRoute } from '@tanstack/react-router';
import { ComplaintDetail } from '@/components/civic/CitizenPages';
import { complaintsQuery } from '@/components/civic/shared';
import { civicHead } from '@/lib/civic-head';
export const Route = createFileRoute('/complaints/$id')({ head: ({params}) => civicHead(`Complaint ${params.id}`, 'View official case updates, department accountability and proposed resolution evidence.'), loader: async ({ context }) => { await context.queryClient.ensureQueryData(complaintsQuery); }, component: Page });
function Page() { const {id}=Route.useParams();return <ComplaintDetail id={id}/>; }
