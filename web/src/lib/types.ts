// Shapes of the API's answers, as served at /api/schema/. Lists that page return
// { next, previous, results }; follow `next` for more.

export type Role = "CITIZEN" | "OFFICER" | "ADMIN";
export type Lang = "bn" | "en";

export type Status =
  | "DRAFT"
  | "SUBMITTED"
  | "ASSIGNED"
  | "IN_PROGRESS"
  | "AWAITING_CITIZEN"
  | "RESOLVED"
  | "REJECTED"
  | "WITHDRAWN";

export const OPEN_STATUSES: Status[] = ["SUBMITTED", "ASSIGNED", "IN_PROGRESS", "AWAITING_CITIZEN"];

export type Priority = "LOW" | "NORMAL" | "HIGH" | "URGENT";
export type PauseReason = "MISSING_DOCUMENT" | "UNCLEAR_REQUEST" | "VERIFICATION" | "OTHER";
export type RejectionReason = "INCOMPLETE" | "NOT_ELIGIBLE" | "DUPLICATE" | "WRONG_OFFICE" | "OTHER";
export type Relation = "SPOUSE" | "CHILD" | "PARENT" | "SIBLING" | "OTHER";
export type BreakGlassReason =
  | "SUPERVISOR_REVIEW"
  | "CITIZEN_COMPLAINT"
  | "AUDIT"
  | "DATA_CORRECTION"
  | "OTHER";

export interface Page<T> {
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface Tokens {
  access: string;
  refresh: string;
  session_id: string;
  token_type: string;
  expires_in: number;
}

export interface LoginOut extends Partial<Tokens> {
  device_token: string;
  mfa_required: boolean;
  mfa_token?: string;
}

export interface Accepted {
  detail: string;
  resend_after: number;
}

export interface Me {
  id: string;
  phone: string;
  full_name: string;
  email: string;
  preferred_language: Lang;
  role: Role;
  department: string | null;
  phone_verified: boolean;
  email_verified: boolean;
  two_step_login: boolean;
}

export interface Session {
  id: string;
  trust_mode: string;
  user_agent: string;
  last_used_at: string;
  expires_at: string;
  current: boolean;
}

export interface Named {
  code: string;
  name_bn: string;
  name_en: string;
}

export interface Category extends Named {
  department: string;
  target_working_days: number;
}

export interface CategoryAdmin extends Category {
  is_active: boolean;
  created_at: string;
}

export interface Department extends Named {
  is_active: boolean;
  created_at: string;
}

export interface RequestRow {
  id: string;
  tracking_no: string | null;
  status: Status;
  title?: string; // citizens
  category: string;
  submitted_at: string | null;
  due_at: string | null;
  priority?: Priority; // staff
  citizen_urgent?: boolean; // staff
  owner_initials?: string; // staff
}

export interface ServiceRequest {
  id: string;
  tracking_no: string | null;
  status: Status;
  category: Named;
  title: string;
  description: string;
  beneficiary: { name: string; relation: string } | null;
  citizen_urgent: boolean;
  urgency_reason: string | null;
  priority: Priority;
  handled_by: { role: string; department: Named } | null;
  submitted_at: string | null;
  due_at: string | null;
  resolved_at: string | null;
  closed_at: string | null;
  reopen_deadline: string | null;
  resolution_note: string | null;
  rejection_reason_code: RejectionReason | "" | null;
  rejection_note: string | null;
  info_request_count: number;
  reopen_count: number;
  version: number;
  created_at: string;
  updated_at: string;
  // staff only
  owner?: { id: string; name: string; phone: string };
  assigned_officer?: { id: string; name: string } | null;
  reassignment_count?: number;
}

export interface TimelineEvent {
  type: string;
  from_status: string;
  to_status: string;
  actor_role: string;
  data: Record<string, unknown> | null;
  at: string;
  actor?: string | null; // staff only
  is_public?: boolean; // staff only
}

export interface Comment {
  id: string;
  body: string;
  internal: boolean;
  author: { role: string; department: string | null; name?: string };
  created_at: string;
}

export type AttachmentStatus = "PENDING" | "VERIFYING" | "READY" | "REJECTED";

export interface Attachment {
  id: string;
  name: string;
  content_type: string;
  size: number;
  status: AttachmentStatus;
  rejection_reason: string | null;
  sha256: string | null;
  created_at: string;
  verified_at: string | null;
}

export interface AttachmentCreated extends Attachment {
  upload: { method: string; url: string; headers: Record<string, string>; expires_at: string };
}

export interface AccessEntry {
  kind: "VIEW" | "UPDATE" | "DOWNLOAD" | "LIST";
  at: string;
  role: string;
  office: Named;
  break_glass: boolean;
  actor: { id: string; name: string };
  break_glass_reason: BreakGlassReason | "" | null;
  break_glass_note: string | null;
}

export interface BreakGlassEntry extends AccessEntry {
  request: { id: string; tracking_no: string };
}

export interface Queue {
  waiting: number;
  requests: RequestRow[];
}

export interface User {
  id: string;
  phone: string;
  full_name: string;
  role: Role;
  department: string | null;
  is_active: boolean;
  phone_verified: boolean;
  two_step_login: boolean;
  has_password: boolean;
  last_login: string | null;
  created_at: string;
}

export interface Holiday {
  date: string;
  name_bn: string;
  name_en: string;
  created_at: string;
}

export interface Suspension {
  id: number;
  department: string | null;
  starts_on: string;
  ends_on: string;
  reason: string;
  created_at: string;
}

export interface Review {
  id: string;
  request: {
    id: string;
    tracking_no: string;
    status: string;
    department: string;
    category: string;
    resolution_note: string | null;
    rejection_reason_code: string | null;
    rejection_note: string | null;
  };
  reason: "LATE_REJECTION" | "SAMPLE";
  decided_status: Status;
  officer: { id: string; full_name: string };
  status: "PENDING" | "UPHELD" | "OVERTURNED";
  reviewer: { id: string; full_name: string } | null;
  note: string | null;
  reviewed_at: string | null;
  created_at: string;
}

export interface Metrics {
  counts: {
    submitted: number;
    open: number;
    overdue: number;
    resolved: number;
    rejected: number;
    withdrawn: number;
  };
  primary: {
    on_time_resolution_rate: number | null;
    median_days_to_resolve: number | null;
    resolution_rate: number | null;
    resolved: number;
  };
  counter: {
    info_request_rate: number | null;
    median_days_paused: number | null;
    rejection_rate: number | null;
    late_rejections: number;
    reopen_rate_after_resolution: number | null;
    reopen_rate_after_rejection: number | null;
    reassignment_rate: number | null;
    withdrawn_after_deadline: number;
  };
}

export interface Stats {
  by: "department" | "category" | "officer";
  from: string;
  to: string;
  totals: Metrics;
  groups: (Metrics & { group: { code: string | null; name: string | null } })[];
}

export interface DemoSms {
  body: string;
  created_at: string;
}
