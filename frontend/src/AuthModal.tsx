import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { serverApi } from './serverApi'
import type { AuthUser, DemoAccount, DemoRole } from './serverApi'

type Props = {
  inline?: boolean
  currentUser: AuthUser | null
  onAuthenticated: (user: AuthUser) => void
  onClose?: () => void
}

const ROLE_LABELS: Record<DemoRole, string> = {
  creator: 'Creator',
  manager: 'Manager',
  authorised_reviewer: 'Final Reviewer',
}

export default function AuthModal({ inline = false, currentUser, onAuthenticated, onClose }: Props) {
  const [mode, setMode] = useState<'quick' | 'login' | 'register'>('quick')
  const [accounts, setAccounts] = useState<DemoAccount[]>([])
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [orgName, setOrgName] = useState('')
  const [role, setRole] = useState<DemoRole>('creator')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    void serverApi
      .authAccounts()
      .then((list) => {
        if (active) setAccounts(list)
      })
      .catch(() => {
        /* ignore if offline */
      })
    return () => {
      active = false
    }
  }, [])

  async function quickSignIn(acc: DemoAccount) {
    setBusy(true)
    setError('')
    try {
      const res = await serverApi.login(acc.email, acc.demo_password)
      onAuthenticated(res.user)
      onClose?.()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign-in failed.')
    } finally {
      setBusy(false)
    }
  }

  async function handleLogin(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const res = await serverApi.login(email.trim(), password)
      onAuthenticated(res.user)
      onClose?.()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Invalid credentials.')
    } finally {
      setBusy(false)
    }
  }

  async function handleRegister(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const res = await serverApi.register({
        email: email.trim(),
        password,
        name: name.trim(),
        role,
        org_name: orgName.trim(),
      })
      onAuthenticated(res.user)
      onClose?.()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Registration failed.')
    } finally {
      setBusy(false)
    }
  }

  const orgGroups = accounts.reduce<Record<string, DemoAccount[]>>((acc, item) => {
    const key = item.org_name || item.org_id
    if (!acc[key]) acc[key] = []
    acc[key].push(item)
    return acc
  }, {})

  const content = (
    <div className="auth-card page-enter" role={inline ? undefined : 'dialog'} aria-modal={!inline}>
      <div className="auth-header">
        <div>
          <span className="workspace-kicker">Organisation Workspace Access</span>
          <h2>{currentUser ? 'Switch workspace account' : 'Sign in to Inkloom AI'}</h2>
          <p className="auth-subtitle">
            Each organisation keeps its own brand guidelines, drafts, and role permissions isolated.
          </p>
        </div>
        {onClose && currentUser && (
          <button type="button" className="auth-close" onClick={onClose} aria-label="Close sign in">
            ×
          </button>
        )}
      </div>

      <div className="auth-tabs">
        <button
          type="button"
          className={mode === 'quick' ? 'active' : ''}
          onClick={() => {
            setMode('quick')
            setError('')
          }}
        >
          Workspace Demo Accounts
        </button>
        <button
          type="button"
          className={mode === 'login' ? 'active' : ''}
          onClick={() => {
            setMode('login')
            setError('')
          }}
        >
          Email Sign In
        </button>
        <button
          type="button"
          className={mode === 'register' ? 'active' : ''}
          onClick={() => {
            setMode('register')
            setError('')
          }}
        >
          New Organisation
        </button>
      </div>

      {error && (
        <p className="validation" role="alert">
          {error}
        </p>
      )}

      {mode === 'quick' ? (
        <div className="auth-org-groups">
          {Object.entries(orgGroups).map(([orgTitle, items]) => (
            <section className="auth-org-group" key={orgTitle}>
              <h3>{orgTitle}</h3>
              <div className="auth-account-grid">
                {items.map((acc) => {
                  const isCurrent = currentUser?.user_id === acc.user_id
                  return (
                    <button
                      type="button"
                      key={acc.user_id}
                      className={`auth-account-card${isCurrent ? ' current' : ''}`}
                      disabled={busy}
                      onClick={() => void quickSignIn(acc)}
                    >
                      <div className="auth-account-top">
                        <strong>{acc.name}</strong>
                        <span className={`auth-role-pill role-${acc.role}`}>{ROLE_LABELS[acc.role]}</span>
                      </div>
                      <span className="auth-account-email">{acc.email}</span>
                    </button>
                  )
                })}
              </div>
            </section>
          ))}
        </div>
      ) : mode === 'login' ? (
        <form className="auth-form" onSubmit={(e) => void handleLogin(e)}>
          <label>
            Work email
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="creator@brightleaf.co"
              required
              disabled={busy}
            />
          </label>
          <label>
            Password
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              required
              disabled={busy}
            />
          </label>
          <button type="submit" className="primary-button" disabled={busy}>
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      ) : (
        <form className="auth-form" onSubmit={(e) => void handleRegister(e)}>
          <label>
            Your name
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Alex Rivera"
              required
              disabled={busy}
            />
          </label>
          <label>
            Organisation / Brand name
            <input
              type="text"
              value={orgName}
              onChange={(e) => setOrgName(e.target.value)}
              placeholder="Acme Studio"
              required
              disabled={busy}
            />
          </label>
          <label>
            Role
            <select value={role} onChange={(e) => setRole(e.target.value as DemoRole)} disabled={busy}>
              <option value="creator">Creator (draft &amp; revise)</option>
              <option value="manager">Manager (review &amp; rectify guidelines)</option>
              <option value="authorised_reviewer">Authorised Reviewer (final sign-off)</option>
            </select>
          </label>
          <label>
            Work email
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="alex@acme.co"
              required
              disabled={busy}
            />
          </label>
          <label>
            Password (6+ characters)
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              minLength={6}
              required
              disabled={busy}
            />
          </label>
          <button type="submit" className="primary-button" disabled={busy}>
            {busy ? 'Creating account…' : 'Create & sign in'}
          </button>
        </form>
      )}
    </div>
  )

  if (inline) {
    return <div className="auth-inline-shell">{content}</div>
  }

  return <div className="auth-overlay">{content}</div>
}
