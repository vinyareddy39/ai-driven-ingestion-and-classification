import React, { useState, useEffect } from 'react';
import { EyeOff, Loader2 } from 'lucide-react';

interface AuthenticatedImageProps {
  src: string;
  alt: string;
  className?: string;
}

export const AuthenticatedImage: React.FC<AuthenticatedImageProps> = ({ src, alt, className }) => {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<boolean>(false);

  useEffect(() => {
    let active = true;
    let createdUrl: string | null = null;

    setLoading(true);
    setError(false);

    const token = localStorage.getItem('ecm_token') || 'token-reviewer-secret';
    const role = localStorage.getItem('ecm_role') || 'reviewer';

    fetch(src, {
      headers: {
        'Authorization': `Bearer ${token}`,
        'X-User-Role': role,
      },
    })
      .then((res) => {
        if (!res.ok) {
          throw new Error(`Failed to load image: ${res.status}`);
        }
        return res.blob();
      })
      .then((blob) => {
        if (active) {
          createdUrl = URL.createObjectURL(blob);
          setBlobUrl(createdUrl);
          setLoading(false);
        }
      })
      .catch(() => {
        if (active) {
          setError(true);
          setLoading(false);
        }
      });

    return () => {
      active = false;
      if (createdUrl) {
        URL.revokeObjectURL(createdUrl);
      }
    };
  }, [src]);

  if (loading) {
    return (
      <div className={`flex items-center justify-center bg-slate-900 border border-slate-800 ${className}`}>
        <Loader2 className="w-5 h-5 text-indigo-400 animate-spin" />
      </div>
    );
  }

  if (error || !blobUrl) {
    return (
      <div className={`flex flex-col items-center justify-center bg-slate-900 border border-slate-800 text-slate-500 p-2 text-xs text-center ${className}`}>
        <EyeOff className="w-4 h-4 mb-1 text-slate-400" />
        <span>Restricted Image</span>
      </div>
    );
  }

  return <img src={blobUrl} alt={alt} className={className} />;
};
