export type Role = "REQUESTER" | "EXTERNAL" | "APPROVER" | "MANAGER" | "ADMIN";

export interface Me {
  id: string;
  name: string;
  email: string | null;
  phone: string | null;
  role: Role;
  department: string;
  mfa: { required: boolean; enrolled: boolean; verified: boolean };
}

export interface Photo {
  id: string;
  caption: string;
  sort_order: number;
  is_cover: boolean;
  urls: Record<string, string>;
}

export interface RoomType {
  id: string;
  name: string;
  description: string;
  capacity: number;
  amenities: string[];
  is_active: boolean;
  price_per_night: string | null;
  room_count: number;
  photos: Photo[];
}

export interface Room {
  id: string;
  number: string;
  room_type: string;
  room_type_name: string;
  floor: number;
  is_active: boolean;
}

export interface Tariff {
  id: string;
  price_per_night: string;
  valid_from: string;
  created_at: string;
}

export interface Availability {
  check_in: string;
  check_out: string;
  nights: number;
  results: { room_type: string; available: number; price_per_night: string | null; amount: string | null }[];
}

export type BookingStatus =
  | "DRAFT" | "PENDING" | "SENT_BACK" | "APPROVED" | "REJECTED" | "CONFIRMED"
  | "ALLOTTED" | "CHECKED_IN" | "CHECKED_OUT" | "CANCELLED" | "EXPIRED" | "NO_SHOW";

export interface Guest {
  id: string;
  name: string;
  phone?: string;
  address?: string;
  id_type?: string;
  has_id_document?: boolean;
  id_document?: string | null;
}

export interface StudentLink {
  student_name: string;
  roll_number: string;
  programme: string;
  year: number;
  relationship: string;
  record_check?: string;
}

export interface BookingDocument {
  id: string;
  type: "RECOMMENDATION_LETTER" | "GUEST_ID";
  guest: string | null;
  content_type: string;
  size: number;
  created_at: string;
}

export interface Booking {
  id: string;
  reference: string;
  status: BookingStatus;
  status_label: string;
  category: "OFFICIAL" | "PERSONAL";
  purpose: string;
  check_in: string;
  check_out: string;
  nights: number;
  room_type: string;
  room_type_name: string;
  room: string | null;
  room_number: string | null;
  price_per_night: string;
  amount: string;
  hold_expires_at: string | null;
  submitted_at: string | null;
  created_at: string;
  requester: { id: string; name: string; email: string | null; phone: string | null; department: string; role: Role };
  guests: Guest[];
  student_link: StudentLink | null;
  documents: BookingDocument[];
  approvals: { id: string; decision: string; comment: string; approver_name: string; decided_at: string }[];
  actions: { edit: boolean; submit: boolean; cancel: boolean; decide: boolean; pay: boolean; allot: boolean };
}

export interface Page<T> {
  count: number;
  next: string | null;
  results: T[];
}

export interface AdminUser {
  id: string;
  name: string;
  email: string | null;
  phone: string | null;
  role: Role;
  department: string;
  is_active: boolean;
  last_login: string | null;
}

export interface ApprovalRule {
  id: string;
  category: "OFFICIAL" | "PERSONAL";
  approver: string;
  approver_name: string;
}

export interface AuditEntry {
  id: string;
  actor_name: string;
  action: string;
  entity: string;
  entity_id: string;
  before: unknown;
  after: unknown;
  ip: string | null;
  created_at: string;
}
