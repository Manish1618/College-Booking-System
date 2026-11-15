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
  id_verified?: boolean;
  in_register?: boolean;
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
  /** Money in and out. Only the booking's owner and the desk receive it. */
  payment: PaymentSummary | null;
  /** The change of dates that is open on a paid booking, or else the last one that was asked for. */
  date_change: DateChange | null;
  actions: {
    edit: boolean;
    submit: boolean;
    cancel: boolean;
    decide: boolean;
    pay: boolean;
    allot: boolean;
    check_in: boolean;
    check_out: boolean;
    refund: boolean;
    receipt: boolean;
    change_dates: boolean;
    decide_change: boolean;
    withdraw_change: boolean;
  };
}

/** New dates asked for on a paid booking. The booking keeps its own dates until this is applied. */
export interface DateChange {
  id: string;
  status: "PENDING" | "AWAITING_PAYMENT" | "APPLIED" | "REJECTED" | "WITHDRAWN" | "EXPIRED";
  status_label: string;
  open: boolean;
  check_in: string;
  check_out: string;
  nights: number;
  amount: string;
  /** What the guest pays if the new stay costs more. */
  balance: string;
  /** What goes back to the guest if it costs less. */
  refund: string;
  old_check_in: string;
  old_check_out: string;
  old_amount: string;
  expires_at: string;
  comment: string;
  requested_at: string;
}

export interface Payment {
  id: string;
  gateway: string;
  gateway_label: string;
  order_id: string;
  gateway_payment_id: string;
  amount: string;
  status: "CREATED" | "PAID" | "FAILED" | "REFUNDED";
  refunded_amount: string;
  failure_reason: string;
  paid_at: string | null;
  created_at: string;
}

export interface Refund {
  id: string;
  booking: string;
  reference: string;
  requester_name: string;
  gateway_label: string;
  amount: string;
  /** The most the amount can be changed to before it is issued. Null once issued. */
  limit: string | null;
  status: "DUE" | "PROCESSING" | "PROCESSED" | "FAILED";
  status_label: string;
  reason: string;
  manual: boolean;
  note: string;
  failure_reason: string;
  created_at: string;
  processed_at: string | null;
}

export interface PaymentSummary {
  paid: string;
  refunded: string;
  payments: Payment[];
  refunds: Refund[];
  refundable: string;
  refund_on_cancel: { percent: number; amount: string; full: string } | null;
  /** What can be paid right now: the booking's charge, or the balance for an approved change of dates. */
  due: string;
  /** An order is open with a gateway and its outcome is not known yet. */
  pending: boolean;
  receipt: boolean;
}

/** What the browser needs to pay an order. The shape depends on the gateway. */
export type Checkout =
  | { mode: "dev"; order_id: string }
  | { mode: "razorpay"; script: string; options: Record<string, unknown> }
  | { mode: "redirect"; action: string; fields: Record<string, string> };

export interface DeskDay {
  date: string;
  arrivals: Booking[];
  departures: Booking[];
  in_house: Booking[];
  to_allot: number;
  refunds_due: number;
  out_of_service: RoomBlock[];
}

/** A room out of service from starts_on until the day before ends_on, the day it is back. */
export interface RoomBlock {
  id: string;
  room: string;
  room_number: string;
  room_type_name: string;
  starts_on: string;
  ends_on: string;
  nights: number;
  reason: string;
  created_by_name: string | null;
  created_at: string;
}

export interface ReportDay {
  date: string;
  available: number;
  sold: number;
  percent: number | null;
  received: string;
  refunded: string;
}

export interface Report {
  from: string;
  to: string;
  days: number;
  occupancy: {
    room_nights_available: number;
    room_nights_sold: number;
    percent: number | null;
    by_room_type: {
      room_type: string;
      name: string;
      rooms: number;
      available: number;
      sold: number;
      percent: number | null;
    }[];
  };
  revenue: {
    received: string;
    refunded: string;
    net: string;
    by_gateway: { gateway: string; label: string; received: string; refunded: string }[];
    refunds_outstanding: string;
  };
  approvals: {
    waiting: number;
    oldest_waiting_since: string | null;
    decided: { approved: number; rejected: number; sent_back: number };
    median_hours: number | null;
  };
  no_shows: {
    count: number;
    bookings: {
      id: string;
      reference: string;
      requester_name: string;
      room_type_name: string;
      check_in: string;
      nights: number;
      kept: string;
    }[];
  };
  bookings: { requested: number; stays: number; cancelled: number };
  daily: ReportDay[];
}

export interface RegisterEntry {
  id: string;
  serial_number: number;
  booking: string;
  booking_reference: string;
  guest_name: string;
  guest_phone: string;
  guest_address: string;
  id_type: string;
  room_number: string;
  arrival_at: string;
  departure_at: string | null;
  purpose: string;
  amount_paid: string;
  entered_by_name: string;
}

export interface Page<T> {
  count: number;
  next: string | null;
  previous: string | null;
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

export const ID_TYPES = [
  ["AADHAAR", "Aadhaar"],
  ["PASSPORT", "Passport"],
  ["DRIVING_LICENCE", "Driving licence"],
  ["VOTER_ID", "Voter ID"],
  ["PAN", "PAN card"],
  ["OTHER", "Other government ID"],
] as const;
