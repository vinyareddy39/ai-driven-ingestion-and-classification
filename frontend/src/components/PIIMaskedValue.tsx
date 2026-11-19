import React, { useState } from 'react';
import { Eye, EyeOff, ShieldAlert } from 'lucide-react';
import { getActiveRole } from '../api/client';

interface PIIMaskedValueProps {
  value: string;
  piiType?: string;
  documentUid?: string;
  position?: Record<string, any>;
  className?: string;
}

/**
 * Mask PII by default (show type and position, reveal on click with role gating).
 * Calls server audit endpoint on reveal, recording user, document, entity type and position,
 * never logging the plaintext value.
 */
export const PIIMaskedValue: React.FC<PIIMaskedValueProps> = ({
  value,
  piiType = 'PII',
  documentUid,
  position,
  className = '',
}) => {
  const [revealed, setRevealed] = useState(false);
  const [loading, setLoading] = useState(false);
  const role = getActiveRole();
  const canReveal = role === 'admin' || role === 'compliance' || role === 'reviewer';

  const maskedRepresentation = `[${piiType}: ••••••••]`;

  const handleToggle = async () => {
    if (!canReveal) {
      alert(`Role '${role}' is not authorized to unmask sensitive ${piiType} records.`);
      return;
    }

    if (!revealed) {
      if (documentUid) {
        setLoading(true);
        try {
          const token = localStorage.getItem('ecm_token') || 'token-reviewer-secret';
          await fetch(`/api/v1/documents/${documentUid}/pii/reveal`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'Authorization': `Bearer ${token}`,
              'X-User-Role': role,
            },
            body: JSON.stringify({
              entity_type: piiType,
              position: position || null,
            }),
          });
        } catch (e) {
          console.warn('Failed to audit PII reveal event:', e);
        } finally {
          setLoading(false);
        }
      }
      setRevealed(true);
    } else {
      setRevealed(false);
    }
  };

  return (
    <span className={`inline-flex items-center gap-1.5 font-mono text-xs px-2 py-0.5 rounded border transition-colors ${
      revealed 
        ? 'bg-rose-950/40 border-rose-700/60 text-rose-200' 
        : 'bg-slate-800/80 border-slate-700 text-slate-300'
    } ${className}`}>
      <ShieldAlert className={`w-3.5 h-3.5 ${revealed ? 'text-rose-400' : 'text-amber-400'}`} />
      <span>{revealed ? value : maskedRepresentation}</span>
      <button
        type="button"
        disabled={loading}
        onClick={handleToggle}
        className="ml-1 text-slate-400 hover:text-slate-100 p-0.5 focus:outline-none disabled:opacity-50"
        title={revealed ? 'Hide PII' : canReveal ? 'Click to reveal PII (Audit Logged)' : 'Restricted Role'}
      >
        {revealed ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
      </button>
    </span>
  );
};
