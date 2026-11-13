"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { QRCodeSVG } from "qrcode.react";
import { useEffect, useRef, useState } from "react";

import { Button, Card, Field, Input, Notice, PageTitle } from "@/components/ui";
import { api } from "@/lib/api";
import { useMe, useRefresh } from "@/lib/hooks";
import type { Me } from "@/lib/types";

export default function LoginPage() {
  const { data: me, isLoading } = useMe();
  const refresh = useRefresh();
  const router = useRouter();
  const next = useSearchParams().get("next");
  const destination = next?.startsWith("/") && !next.startsWith("//") ? next : "/bookings";

  const [identifier, setIdentifier] = useState("");
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [sent, setSent] = useState<{ channel: string; debug_code?: string } | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [setup, setSetup] = useState({ oidc_enabled: false, turnstile_site_key: "" });
  const [challenge, setChallenge] = useState({ token: "", round: 0 });
  const oidc = setup.oidc_enabled;
  const siteKey = setup.turnstile_site_key;

  useEffect(() => {
    api<typeof setup>("/auth/csrf").then(setSetup).catch(() => {});
  }, []);

  const needsMfa = !!me && me.mfa.required && !me.mfa.verified;
  useEffect(() => {
    if (me && !needsMfa) {
      if (destination.startsWith("/django-admin")) window.location.assign(destination);
      else router.replace(destination);
    }
  }, [me, needsMfa, destination, router]);

  async function run(action: () => Promise<unknown>) {
    setError("");
    setBusy(true);
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  if (isLoading) return null;
  if (needsMfa && me) return <TotpStep me={me} onDone={refresh} />;
  if (me) return null;

  return (
    <div className="mx-auto max-w-md">
      <PageTitle title="Sign in">We will send a one-time code. No password needed.</PageTitle>
      <Card>
        {error && (
          <div className="mb-4">
            <Notice tone="error">{error}</Notice>
          </div>
        )}
        {!sent ? (
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              run(async () => {
                try {
                  setSent(await api("/auth/otp/request", { body: { identifier, turnstile_token: challenge.token } }));
                } finally {
                  // A Turnstile token works once, so start a fresh challenge whatever happened.
                  setChallenge((c) => ({ token: "", round: c.round + 1 }));
                }
              });
            }}
          >
            <Field label="Email or mobile number" hint="College members: use your college email address.">
              <Input
                required
                autoFocus
                autoComplete="username"
                inputMode="email"
                value={identifier}
                onChange={(e) => setIdentifier(e.target.value)}
              />
            </Field>
            {siteKey && (
              <Turnstile
                key={challenge.round}
                siteKey={siteKey}
                onToken={(token) => setChallenge((c) => ({ ...c, token }))}
              />
            )}
            <Button type="submit" disabled={busy || (!!siteKey && !challenge.token)} className="w-full">
              Send code
            </Button>
            {oidc && (
              <a
                href="/api/auth/oidc/authenticate/"
                className="flex min-h-11 items-center justify-center rounded-md border border-slate-300 text-sm font-medium"
              >
                Sign in with college SSO
              </a>
            )}
          </form>
        ) : (
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              run(async () => {
                await api("/auth/otp/verify", { body: { identifier, code, name } });
                await refresh();
              });
            }}
          >
            <Notice>
              We sent a 6-digit code to {identifier} by {sent.channel === "phone" ? "SMS" : "email"}.
              {sent.debug_code && (
                <>
                  {" "}
                  Development mode: your code is <strong>{sent.debug_code}</strong>.
                </>
              )}
            </Notice>
            <Field label="Sign-in code">
              <Input
                required
                autoFocus
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="[0-9]{6}"
                maxLength={6}
                value={code}
                onChange={(e) => setCode(e.target.value)}
              />
            </Field>
            <Field label="Your name" hint="Only needed the first time you sign in.">
              <Input autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <Button type="submit" disabled={busy} className="w-full">
              Sign in
            </Button>
            <button
              type="button"
              className="w-full py-2 text-sm text-brand-700 hover:underline"
              onClick={() => {
                setSent(null);
                setCode("");
              }}
            >
              Use a different address
            </button>
          </form>
        )}
      </Card>
      <p className="mt-4 text-center text-sm text-slate-600">
        <Link href="/" className="text-brand-700 hover:underline">
          Back to rooms
        </Link>
      </p>
    </div>
  );
}

function TotpStep({ me, onDone }: { me: Me; onDone: () => void }) {
  const [url, setUrl] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!me.mfa.enrolled) {
      api<{ otpauth_url: string }>("/auth/totp/setup", { method: "POST" })
        .then((r) => setUrl(r.otpauth_url))
        .catch((e) => setError(e.message));
    }
  }, [me.mfa.enrolled]);

  const secret = url ? new URL(url).searchParams.get("secret") : null;

  return (
    <div className="mx-auto max-w-md">
      <PageTitle title="Two-step verification">
        {me.mfa.enrolled
          ? "Enter the 6-digit code from your authenticator app."
          : "Staff accounts need an authenticator app. Scan the code, then enter the 6 digits it shows."}
      </PageTitle>
      <Card>
        <form
          className="space-y-4"
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            setError("");
            try {
              await api("/auth/totp/verify", { body: { code } });
              onDone();
            } catch (err) {
              setError(err instanceof Error ? err.message : "Something went wrong.");
            } finally {
              setBusy(false);
            }
          }}
        >
          {error && <Notice tone="error">{error}</Notice>}
          {url && (
            <div className="flex flex-col items-center gap-2">
              <QRCodeSVG value={url} size={176} title="Authenticator setup code" />
              <p className="break-all text-center text-sm text-slate-600">
                Or enter this key by hand: <code className="font-mono">{secret}</code>
              </p>
            </div>
          )}
          <Field label="Authenticator code">
            <Input
              required
              autoFocus
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="[0-9]{6}"
              maxLength={6}
              value={code}
              onChange={(e) => setCode(e.target.value)}
            />
          </Field>
          <Button type="submit" disabled={busy} className="w-full">
            Verify
          </Button>
        </form>
      </Card>
    </div>
  );
}

type TurnstileApi = {
  render: (el: HTMLElement, options: Record<string, unknown>) => string;
  remove: (id: string) => void;
};

/** Cloudflare Turnstile challenge. Reports a token when solved and an empty string when it lapses. */
function Turnstile({ siteKey, onToken }: { siteKey: string; onToken: (token: string) => void }) {
  const box = useRef<HTMLDivElement>(null);
  const report = useRef(onToken);
  useEffect(() => {
    report.current = onToken;
  });

  useEffect(() => {
    const turnstile = () => (window as unknown as { turnstile?: TurnstileApi }).turnstile;
    let widget: string | undefined;
    let gone = false;
    const render = () => {
      if (gone || !box.current || !turnstile()) return;
      widget = turnstile()!.render(box.current, {
        sitekey: siteKey,
        callback: (token: string) => report.current(token),
        "expired-callback": () => report.current(""),
        "error-callback": () => report.current(""),
      });
    };
    if (turnstile()) render();
    else {
      const src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
      let script = document.querySelector<HTMLScriptElement>(`script[src="${src}"]`);
      if (!script) {
        script = document.createElement("script");
        script.src = src;
        script.async = true;
        document.head.appendChild(script);
      }
      script.addEventListener("load", render);
    }
    return () => {
      gone = true;
      if (widget) turnstile()?.remove(widget);
    };
  }, [siteKey]);

  return <div ref={box} />;
}
