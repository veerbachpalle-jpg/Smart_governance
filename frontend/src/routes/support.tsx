import { createFileRoute } from '@tanstack/react-router';
import { SupportPage } from '@/components/civic/CitizenPages';
import { civicHead } from '@/lib/civic-head';
export const Route = createFileRoute('/support')({ validateSearch: (s: Record<string, unknown>): { section?: string } => (typeof s['section'] === 'string' ? { section: s['section'] } : {}), head: () => civicHead('Support and privacy', 'CivicSense complaint assistance, privacy information, and accessibility support.'), component: Page });
function Page() { const {section}=Route.useSearch();return <SupportPage {...(section ? { section } : {})}/>; }
