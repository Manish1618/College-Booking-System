"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Button, Card, Field, Input, inputClass, Loading, Notice, PageTitle } from "@/components/ui";
import { api, apiAll, fmtDateTime } from "@/lib/api";
import { isAdmin, useMe, useRefresh } from "@/lib/hooks";
import type { AdminUser, ApprovalRule, AuditEntry, Page, Role } from "@/lib/types";

const ROLES: [Role, string][] = [
  ["REQUESTER", "College requester"],
  ["EXTERNAL", "External guest"],
  ["APPROVER", "Approver"],
  ["MANAGER", "Guesthouse manager"],
  ["ADMIN", "Super admin"],
];

export default function AdminPage() {
  const { data: me, isLoading } = useMe();
  const allowed = isAdmin(me);
  const refresh = useRefresh();
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");

  const users = useQuery({
    queryKey: ["users", search],
    queryFn: () => api<Page<AdminUser>>(`/users?q=${encodeURIComponent(search)}`),
    enabled: allowed,
  });
  const approvers = useQuery({
    queryKey: ["users", "approvers"],
    queryFn: () => apiAll<AdminUser>("/users?role=APPROVER"),
    enabled: allowed,
  });
  const rules = useQuery({ queryKey: ["approval-rules"], queryFn: () => api<ApprovalRule[]>("/approval-rules"), enabled: allowed });
  const audit = useQuery({ queryKey: ["audit"], queryFn: () => api<Page<AuditEntry>>("/audit-logs"), enabled: allowed });

  async function run(action: () => Promise<unknown>) {
    setError("");
    try {
      await action();
      await refresh();
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
      return false;
    }
  }

  if (isLoading) return <Loading />;
  if (!allowed) return <Notice tone="error">This page is for super admins.</Notice>;

  return (
    <div className="space-y-6">
      <PageTitle title="Administration" />
      {error && <Notice tone="error">{error}</Notice>}

      <Card>
        <h2 className="mb-3 text-lg font-semibold">Users and roles</h2>
        <AddUser run={run} />
        <div className="mt-5">
          <Field label="Search users">
            <Input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Name, email or phone" />
          </Field>
        </div>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[36rem] text-left text-sm">
            <thead className="text-slate-600">
              <tr>
                <th scope="col" className="py-2 font-medium">Name</th>
                <th scope="col" className="py-2 font-medium">Sign-in</th>
                <th scope="col" className="py-2 font-medium">Role</th>
                <th scope="col" className="py-2 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {users.data?.results.map((user) => (
                <tr key={user.id} className="border-t border-slate-100">
                  <td className="py-2">
                    {user.name || "—"}
                    {user.department && <span className="block text-slate-600">{user.department}</span>}
                  </td>
                  <td className="py-2">{user.email ?? user.phone}</td>
                  <td className="py-2">
                    <select
                      aria-label={`Role for ${user.name || user.email || user.phone}`}
                      value={user.role}
                      disabled={user.id === me?.id}
                      onChange={(e) => run(() => api(`/users/${user.id}`, { method: "PATCH", body: { role: e.target.value } }))}
                      className="min-h-9 rounded-md border border-slate-300 bg-white px-2"
                    >
                      {ROLES.map(([value, label]) => (
                        <option key={value} value={value}>
                          {label}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="py-2">
                    <button
                      type="button"
                      disabled={user.id === me?.id}
                      className="py-1 text-brand-700 hover:underline disabled:text-slate-400 disabled:no-underline"
                      onClick={() => run(() => api(`/users/${user.id}`, { method: "PATCH", body: { is_active: !user.is_active } }))}
                    >
                      {user.is_active ? "Active · disable" : "Disabled · enable"}
                    </button>
                    {(user.role === "MANAGER" || user.role === "ADMIN") && user.id !== me?.id && (
                      <button
                        type="button"
                        className="ml-3 py-1 text-brand-700 hover:underline"
                        onClick={() =>
                          window.confirm("Reset two-step verification for this user? They will set it up again at next sign-in.") &&
                          run(() => api(`/users/${user.id}/reset-mfa`, { method: "POST" }))
                        }
                      >
                        Reset two-step
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {users.data && users.data.count > users.data.results.length && (
          <p className="mt-2 text-sm text-slate-600">
            Showing the first {users.data.results.length} of {users.data.count} users. Search to find the others.
          </p>
        )}
      </Card>

      <Card>
        <h2 className="mb-1 text-lg font-semibold">Approval rules</h2>
        <p className="mb-3 text-sm text-slate-600">
          Choose who decides each kind of stay. A kind with no rule can be decided by any approver.
        </p>
        <ul className="mb-4 space-y-1 text-sm">
          {rules.data?.map((rule) => (
            <li key={rule.id} className="flex items-center justify-between border-b border-slate-100 py-1.5">
              <span>
                {rule.category === "OFFICIAL" ? "Official stays" : "Personal stays"}: <strong>{rule.approver_name}</strong>
              </span>
              <button type="button" className="py-1 text-red-700 hover:underline" onClick={() => run(() => api(`/approval-rules/${rule.id}`, { method: "DELETE" }))}>
                Remove
              </button>
            </li>
          ))}
          {rules.data?.length === 0 && <li className="text-slate-600">No rules yet.</li>}
        </ul>
        <AddRule approvers={approvers.data ?? []} run={run} />
      </Card>

      <Card>
        <h2 className="mb-3 text-lg font-semibold">Audit log</h2>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[40rem] text-left text-sm">
            <thead className="text-slate-600">
              <tr>
                <th scope="col" className="py-2 font-medium">When</th>
                <th scope="col" className="py-2 font-medium">Who</th>
                <th scope="col" className="py-2 font-medium">Action</th>
                <th scope="col" className="py-2 font-medium">Details</th>
              </tr>
            </thead>
            <tbody>
              {audit.data?.results.map((entry) => (
                <tr key={entry.id} className="border-t border-slate-100 align-top">
                  <td className="whitespace-nowrap py-2 pr-3">{fmtDateTime(entry.created_at)}</td>
                  <td className="py-2 pr-3">
                    {entry.actor_name}
                    {entry.ip && <span className="block text-slate-500">{entry.ip}</span>}
                  </td>
                  <td className="py-2 pr-3 font-mono text-xs">{entry.action}</td>
                  <td className="max-w-xs break-words py-2 font-mono text-xs text-slate-600">
                    {entry.after ? JSON.stringify(entry.after) : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {audit.data && audit.data.count > audit.data.results.length && (
          <p className="mt-3 text-sm text-slate-600">
            Showing the latest {audit.data.results.length} of {audit.data.count} entries.
          </p>
        )}
      </Card>
    </div>
  );
}

function AddUser({ run }: { run: (action: () => Promise<unknown>) => Promise<boolean> }) {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<Role>("APPROVER");
  return (
    <form
      className="grid items-end gap-3 sm:grid-cols-[1fr_1fr_auto_auto]"
      onSubmit={async (e) => {
        e.preventDefault();
        if (await run(() => api("/users", { body: { email, name, role } }))) {
          setEmail("");
          setName("");
        }
      }}
    >
      <Field label="Email">
        <Input required type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
      </Field>
      <Field label="Name">
        <Input value={name} onChange={(e) => setName(e.target.value)} />
      </Field>
      <Field label="Role">
        <select value={role} onChange={(e) => setRole(e.target.value as Role)} className={inputClass}>
          {ROLES.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </Field>
      <Button type="submit" variant="secondary">
        Add user
      </Button>
    </form>
  );
}

function AddRule({ approvers, run }: { approvers: AdminUser[]; run: (action: () => Promise<unknown>) => Promise<boolean> }) {
  const [category, setCategory] = useState("OFFICIAL");
  const [approver, setApprover] = useState("");
  return (
    <form
      className="flex flex-wrap items-end gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        run(() => api("/approval-rules", { body: { category, approver } }));
      }}
    >
      <Field label="Kind of stay">
        <select value={category} onChange={(e) => setCategory(e.target.value)} className={inputClass}>
          <option value="OFFICIAL">Official stays</option>
          <option value="PERSONAL">Personal stays</option>
        </select>
      </Field>
      <Field label="Approver">
        <select required value={approver} onChange={(e) => setApprover(e.target.value)} className={inputClass}>
          <option value="">Choose an approver</option>
          {approvers.map((user) => (
            <option key={user.id} value={user.id}>
              {user.name || user.email}
            </option>
          ))}
        </select>
      </Field>
      <Button type="submit" variant="secondary">
        Add rule
      </Button>
    </form>
  );
}
