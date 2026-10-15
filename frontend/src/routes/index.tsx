import { createFileRoute } from '@tanstack/react-router';
import Overview from '@/components/civic/Overview';
import { complaintsQuery } from '@/components/civic/shared';
import { civicHead } from '@/lib/civic-head';
export const Route = createFileRoute('/')({ head: () => civicHead('Citizen overview', 'CivicSense citizen services: report civic issues, track complaints, and review proposed resolutions.'), loader: async ({ context }) => { await context.queryClient.ensureQueryData(complaintsQuery); }, component: Overview });
