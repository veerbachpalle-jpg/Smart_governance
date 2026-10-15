import { useSimulation } from '@/lib/civic-sim';
import type { ReactNode } from "react";
import { useEffect, useState } from 'react';
import { Link, useRouterState } from '@tanstack/react-router';
import { useTranslation } from 'react-i18next';
import { Building2, LayoutDashboard, PlusCircle, Files, ScanSearch, Headphones, ArrowUpRight, ShieldCheck, ChevronDown, Bell, Globe2, MapPin, Menu, X, ClipboardList, Scale, SlidersHorizontal, ScrollText, Activity, ArrowLeft, LogOut } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { isDemo, setDemoMode, getIsDemo } from '@/lib/civic-api';
import i18n from '@/lib/civic-i18n';
import type { Role } from '@/lib/civic-types';
import { getSession } from '@/lib/civic-api';
import { toast } from 'sonner';
export function PortalShell({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const pathname = useRouterState({ select: state => state.location.pathname });
  const staff = pathname.startsWith('/staff');
  const [simulation] = useSimulation();
  const [open, setOpen] = useState(false);
  const [role, setRole] = useState<Role>('officer');
  const [demoActive, setDemoActive] = useState<boolean>(getIsDemo);

  useEffect(() => {
    const lang = localStorage.getItem('civic-language');
    if (lang && ['en', 'hi', 'kn'].includes(lang)) void i18n.changeLanguage(lang);
  }, []);
  useEffect(() => { setOpen(false); }, [pathname]);
  useEffect(() => { if (demoActive) sessionStorage.setItem('civic-demo-role', role); }, [role, demoActive]);
  useEffect(() => {
    const handler = (e: Event) => setDemoActive(Boolean((e as CustomEvent).detail));
    window.addEventListener('civic-mode-change', handler);
    return () => window.removeEventListener('civic-mode-change', handler);
  }, []);

  const staffLinks = [
    { label: 'dashboard', view: 'dashboard', icon: LayoutDashboard, roles: ['officer', 'lead', 'supervisor', 'admin', 'auditor'] },
    { label: 'triage', view: 'triage', icon: ScanSearch, roles: ['officer', 'lead', 'supervisor', 'admin'] },
    { label: 'cases', view: 'cases', icon: ClipboardList, roles: ['officer', 'lead', 'supervisor', 'admin'] },
    { label: 'challenges', view: 'challenges', icon: Scale, roles: ['supervisor', 'admin'] },
    { label: 'policies', view: 'policies', icon: SlidersHorizontal, roles: ['admin'] },
    { label: 'audit', view: 'audit', icon: ScrollText, roles: ['auditor', 'supervisor', 'admin'] },
    { label: 'quality', view: 'quality', icon: Activity, roles: ['lead', 'supervisor', 'admin', 'auditor'] },
  ];
  const currentRole = demoActive ? role : getSession()?.role ?? 'citizen';
  return <div>
    <a href="#main-content" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:bg-background focus:p-3">Skip to main content</a>
    {open && <div className="fixed inset-0 z-30 md:hidden" onClick={() => setOpen(false)} />}
    <aside className={`app-sidebar ${open ? 'mobile-open' : ''}`} aria-label="Primary navigation">
      <div className="flex h-[90px] items-center gap-3 px-6"><div className="grid size-10 place-items-center rounded-lg border border-sidebar-border bg-sidebar-accent"><Building2 className="size-6 text-sidebar-active" strokeWidth={1.5} /></div><div><Link to="/" className="font-display text-xl font-bold">CivicSense<span className="text-sidebar-active">.</span></Link><p className="mt-1 text-[7px] tracking-[1.6px] text-sidebar-dim">{t('tagline')}</p></div><Button className="ml-auto text-sidebar-foreground md:hidden" variant="ghost" size="icon" aria-label="Close navigation" onClick={() => setOpen(false)}><X /></Button></div>
      <div className="mx-5 mb-7 flex h-12 items-center gap-3 rounded-md border border-sidebar-border px-3"><span className="grid size-7 place-items-center rounded bg-sidebar-accent"><Building2 className="size-4 text-sidebar-dim" /></span><span className="text-xs font-medium">{t(staff ? 'staffConsole' : 'citizenPortal')}</span><ChevronDown className="ml-auto size-3 text-sidebar-dim" /></div>
      <div className="px-5"><p className="section-label mb-3 px-3 text-sidebar-dim">{staff ? 'WORKSPACE' : 'CITIZEN SERVICES'}</p><nav className="space-y-1">
        {staff ? staffLinks.filter(link => link.roles.includes(currentRole)).map(link => <Link key={link.view} to="/staff/$view" params={{ view: link.view }} className={`nav-item ${pathname === `/staff/${link.view}` ? 'active' : ''}`}><link.icon />{t(link.label)}</Link>) : <>
          <Link to="/" className={`nav-item ${pathname === '/' ? 'active' : ''}`}><LayoutDashboard />{t('overview')}</Link>
          <Link to="/report" className={`nav-item ${pathname === '/report' ? 'active' : ''}`}><PlusCircle />{t('submit')}</Link>
          <Link to="/complaints" className={`nav-item ${pathname.startsWith('/complaints') ? 'active' : ''}`}><Files />{t('myComplaints')}</Link>
          <Link to="/track" className={`nav-item ${pathname === '/track' ? 'active' : ''}`}><ScanSearch />{t('track')}</Link>
        </>}
      </nav></div>
      <div className="mx-5 mt-6 border-t border-sidebar-border pt-6"><p className="section-label mb-3 px-3 text-sidebar-dim">{staff ? 'PORTALS' : 'RESOURCES'}</p><Link to="/support" className={`nav-item ${pathname === '/support' ? 'active' : ''}`}><Headphones />{t('help')}<ArrowUpRight className="ml-auto size-3" /></Link>{staff ? <Link to="/" className="nav-item"><ArrowLeft />{t('citizenPortal')}<ArrowUpRight className="ml-auto size-3" /></Link> : <Link to="/staff/$view" params={{ view: 'dashboard' }} className="nav-item"><ShieldCheck />{t('staffConsole')}<ArrowUpRight className="ml-auto size-3" /></Link>}</div>
      <div className="mt-auto p-5"><div className="border-t border-sidebar-border pt-5"><div className="flex items-center gap-2 text-xs text-sidebar-dim"><ShieldCheck className="size-4 text-sidebar-active" />Human oversight, always</div><p className="mt-2 pl-6 text-[10px] leading-relaxed text-sidebar-dim">Transparent service.<br />Accountable departments.</p></div></div>
      <Link to="/signin" className="flex items-center gap-3 border-t border-sidebar-border px-6 py-5"><div className="grid size-9 place-items-center rounded-full bg-sidebar-accent"><span className="text-sm font-semibold text-sidebar-active">{staff ? 'S' : 'C'}</span></div><div><p className="text-xs font-medium">{demoActive ? (staff ? 'Staff workspace' : 'Citizen workspace') : t('signIn')}</p><p className="mt-1 text-[10px] text-sidebar-dim">{demoActive ? 'Demonstration access' : 'Secure account access'}</p></div><LogOut className="ml-auto size-4 text-sidebar-dim" /></Link>
    </aside>
    <div className="app-body"><header className="flex h-[73px] items-center justify-between gap-3 border-b border-border bg-surface px-5 lg:px-10"><div className="flex items-center gap-3"><Button variant="ghost" size="icon" className="min-h-11 min-w-11 md:hidden" onClick={() => setOpen(true)} aria-label={t('menu')}><Menu /></Button><span className="flex items-center gap-2 text-[12px] font-medium"><MapPin className="size-4 text-primary" />{t('city')}<span className="hidden font-normal text-muted-foreground lg:inline"><span className="mx-3 text-border">/</span>{t('portalName')}</span></span></div><div className="flex items-center gap-4">
      {staff && demoActive && <select aria-label="Demonstration staff role" value={role} onChange={event => setRole(event.target.value as Role)} className="max-w-32 rounded-md border border-input bg-background p-2 text-xs"><option value="officer">Officer</option><option value="lead">Department lead</option><option value="supervisor">Supervisor</option><option value="admin">Administrator</option><option value="auditor">Auditor</option></select>}
      <DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" className="gap-2 px-2"><Globe2 className="size-4 text-muted-foreground" /><span className="hidden sm:inline">{{ en: 'English', hi: 'हिन्दी', kn: 'ಕನ್ನಡ' }[i18n.language] ?? 'English'}</span><ChevronDown className="size-3" /></Button></DropdownMenuTrigger><DropdownMenuContent align="end">{([['en', 'English'], ['hi', 'हिन्दी'], ['kn', 'ಕನ್ನಡ']] as const).map(([lang, label]) => <DropdownMenuItem key={lang} onClick={() => { void i18n.changeLanguage(lang); localStorage.setItem('civic-language', lang); }}>{label}</DropdownMenuItem>)}</DropdownMenuContent></DropdownMenu>
      <span className="h-5 border-l border-border" /><Button variant="ghost" size="icon" className="min-h-11 min-w-11" aria-label={t('notify')} onClick={() => toast.info(demoActive ? 'One sample complaint is awaiting your resolution review.' : 'Sign in to view your notifications.')}><Bell className="size-[18px]" /></Button><Link to="/signin" className="hidden size-8 items-center justify-center rounded-full border border-border bg-secondary text-xs font-semibold text-primary sm:flex" aria-label={t('profile')}>{staff ? 'S' : 'C'}</Link>
    </div></header>
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-background px-5 py-2 text-[10px] text-muted-foreground lg:px-10">
      <span className="flex items-center gap-2">
        <span className={`size-1.5 rounded-full ${demoActive ? 'bg-warning' : 'bg-primary'}`} />
        <span className={`font-semibold tracking-[1px] ${demoActive ? 'text-warning' : 'text-primary'}`}>
          {demoActive ? t('demo') : 'ORIGINAL MODE'}
        </span>
        <span className="hidden sm:inline">
          {demoActive ? t('demoText') : 'Connected to live municipal API services'}
        </span>
      </span>
      <div className="flex items-center gap-4">
        <div className="flex items-center rounded border border-border bg-secondary p-0.5" role="group" aria-label="Portal mode switcher">
          <button
            type="button"
            onClick={() => { setDemoMode(true); toast.info('Demo Mode active — explore all features freely'); }}
            className={`rounded px-2.5 py-0.5 font-medium transition-colors ${demoActive ? 'bg-primary text-primary-foreground font-semibold shadow-xs' : 'text-muted-foreground hover:text-foreground'}`}
          >
            Demo
          </button>
          <button
            type="button"
            onClick={() => { setDemoMode(false); toast.info('Original Mode active — live backend connection'); }}
            className={`rounded px-2.5 py-0.5 font-medium transition-colors ${!demoActive ? 'bg-primary text-primary-foreground font-semibold shadow-xs' : 'text-muted-foreground hover:text-foreground'}`}
          >
            Original
          </button>
        </div>
        <span>English · हिन्दी · ಕನ್ನಡ</span>
      </div>
    </div>
    {staff && simulation.length > 0 && <div role="alert" className="flex items-center gap-2 border-b border-warning/30 bg-warning-soft px-5 py-2 text-xs text-warning lg:px-10"><span className="size-1.5 rounded-full bg-warning" />Failure simulation active: {simulation.join(', ')}. Use manual triage until cleared in Policy settings.</div>}<main id="main-content">{children}</main>
    <footer className="mx-5 flex flex-wrap items-center justify-between gap-3 border-t border-border py-5 text-[10px] text-muted-foreground lg:mx-10"><span>{t('footer')}</span><div className="flex gap-5">{['privacy', 'accessibility', 'support'].map(section => <Link to="/support" search={{ section }} key={section} className="hover:text-primary">{t(section)}</Link>)}</div></footer>
    </div>
  </div>;
}
