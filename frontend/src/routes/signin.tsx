import { createFileRoute } from '@tanstack/react-router';
import { SignInPage } from '@/components/civic/CitizenPages';
import { civicHead } from '@/lib/civic-head';
export const Route = createFileRoute('/signin')({ head: () => civicHead('Sign in', 'Secure account access for CivicSense citizen services and municipal staff.'), component: SignInPage });
