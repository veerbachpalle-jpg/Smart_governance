export type Status =
  "submitted" | "in_progress" | "review" | "resolved" | "challenged" | "reopened";
export type Role = "officer" | "lead" | "supervisor" | "admin" | "auditor";
export type Category =
  | "Roads & footpaths"
  | "Water & drainage"
  | "Street lighting"
  | "Waste management"
  | "Public safety";
export interface Activity {
  title: string;
  note: string;
  department: string;
  date: string;
  public: boolean;
}
export interface Complaint {
  id: string;
  backendId?: string;
  caseId?: string;
  title: string;
  description: string;
  category: Category;
  address: string;
  ward: string;
  lat: number;
  lng: number;
  status: Status;
  date: string;
  department: string;
  priority: "Normal" | "High" | "Critical";
  evidenceVerified: boolean;
  attachments: string[];
  activity: Activity[];
  language: string;
  upvoteCount?: number;
  priorityBand?: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  compositeScore?: number;
  slaDeadline?: string;
  slaSecondsRemaining?: number;
  slaOverdue?: boolean;
  wardNumber?: number;
  resolution?: { notes: string; evidence: string[]; deadline: string; officer: string };
  challenge?: { reason: string; outcome?: string; evidence: string[] };
}
export interface TrendingIssue {
  id: string;
  backendId: string;
  title: string;
  ward: string;
  wardNumber?: number;
  lat: number;
  lng: number;
  status: string;
  distanceMeters: number;
  upvoteCount: number;
  priorityBand: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  compositeScore: number;
  upvoted: boolean;
}
export interface NewComplaint {
  title: string;
  description: string;
  category: Category;
  address: string;
  lat: number;
  lng: number;
  attachments: string[];
  language: string;
}
export interface Tokens {
  accessToken: string;
  refreshToken: string;
  role: Role | "citizen";
}
