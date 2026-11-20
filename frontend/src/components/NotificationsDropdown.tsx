import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Bell, Check, Loader2 } from 'lucide-react';
import { BASE_URL, getAuthToken } from '../api/client';

export interface NotificationItem {
  id: string;
  batch_id?: string | null;
  title: string;
  message: string;
  read: boolean;
  created_at: string;
}

export interface NotificationListResponse {
  items: NotificationItem[];
  unread_count: number;
}

interface NotificationsDropdownProps {
  onSelectBatch?: (batchId: string) => void;
}

export const NotificationsDropdown: React.FC<NotificationsDropdownProps> = ({ onSelectBatch }) => {
  const [isOpen, setIsOpen] = useState(false);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [unreadCount, setUnreadCount] = useState<number>(0);
  const [isLoading, setIsLoading] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const fetchNotifications = useCallback(async () => {
    try {
      const headers: Record<string, string> = {};
      const token = getAuthToken();
      if (token) headers['Authorization'] = `Bearer ${token}`;

      const res = await fetch(`${BASE_URL}/api/v1/notifications`, { headers });
      if (res.ok) {
        const data: NotificationListResponse = await res.json();
        setNotifications(data.items || []);
        setUnreadCount(data.unread_count || 0);
      }
    } catch {
      // Ignore network errors in background poll
    }
  }, []);

  useEffect(() => {
    void fetchNotifications();
    const interval = setInterval(() => {
      void fetchNotifications();
    }, 10_000);
    return () => clearInterval(interval);
  }, [fetchNotifications]);

  // Close when clicking outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleMarkAsRead = async (id: string, batchId?: string | null) => {
    try {
      const headers: Record<string, string> = {};
      const token = getAuthToken();
      if (token) headers['Authorization'] = `Bearer ${token}`;

      await fetch(`${BASE_URL}/api/v1/notifications/${encodeURIComponent(id)}/read`, {
        method: 'POST',
        headers,
      });
      setNotifications((prev) =>
        prev.map((n) => (n.id === id ? { ...n, read: true } : n))
      );
      setUnreadCount((prev) => Math.max(0, prev - 1));
      if (batchId && onSelectBatch) {
        setIsOpen(false);
        onSelectBatch(batchId);
      }
    } catch {
      // Ignore
    }
  };

  const handleMarkAllRead = async () => {
    setIsLoading(true);
    try {
      const headers: Record<string, string> = {};
      const token = getAuthToken();
      if (token) headers['Authorization'] = `Bearer ${token}`;

      await fetch(`${BASE_URL}/api/v1/notifications/read-all`, {
        method: 'POST',
        headers,
      });
      setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
      setUnreadCount(0);
    } catch {
      // Ignore
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        aria-label="Notifications"
        className="relative p-2 rounded-lg text-slate-300 hover:text-white hover:bg-slate-800 transition-colors"
      >
        <Bell className="w-5 h-5" />
        {unreadCount > 0 && (
          <span className="absolute -top-0.5 -right-0.5 min-w-[1.125rem] h-4.5 px-1 bg-teal-500 text-slate-950 text-xs font-bold rounded-full flex items-center justify-center shadow-md animate-pulse">
            {unreadCount > 9 ? '9+' : unreadCount}
          </span>
        )}
      </button>

      {isOpen && (
        <div className="absolute right-0 mt-2 w-80 sm:w-96 rounded-xl bg-slate-900 border border-slate-800 shadow-2xl z-50 overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800/80 bg-slate-950/40">
            <div className="flex items-center space-x-2">
              <span className="font-semibold text-sm text-slate-200">Notifications</span>
              {unreadCount > 0 && (
                <span className="text-xs px-2 py-0.5 rounded-full bg-teal-500/10 text-teal-400 border border-teal-500/30">
                  {unreadCount} new
                </span>
              )}
            </div>
            {unreadCount > 0 && (
              <button
                onClick={handleMarkAllRead}
                disabled={isLoading}
                className="text-xs text-teal-400 hover:text-teal-300 flex items-center space-x-1"
              >
                {isLoading ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />}
                <span>Mark all as read</span>
              </button>
            )}
          </div>

          <div className="max-h-80 overflow-y-auto divide-y divide-slate-800/60">
            {notifications.length === 0 ? (
              <div className="p-6 text-center text-sm text-slate-500">
                No notifications yet.
              </div>
            ) : (
              notifications.map((notif) => (
                <div
                  key={notif.id}
                  onClick={() => handleMarkAsRead(notif.id, notif.batch_id)}
                  className={`p-3.5 cursor-pointer transition-colors hover:bg-slate-800/50 flex items-start space-x-3 ${
                    notif.read ? 'opacity-65 bg-slate-900/40' : 'bg-slate-800/25'
                  }`}
                >
                  <div className="mt-1">
                    {!notif.read ? (
                      <span className="w-2 h-2 rounded-full bg-teal-400 block shadow-sm shadow-teal-400/50" />
                    ) : (
                      <span className="w-2 h-2 rounded-full bg-slate-600 block" />
                    )}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className={`text-sm font-medium ${notif.read ? 'text-slate-300' : 'text-teal-300'}`}>
                      {notif.title}
                    </p>
                    <p className="text-xs text-slate-400 mt-0.5 line-clamp-2">{notif.message}</p>
                    <span className="text-[10px] text-slate-500 mt-1 block">
                      {new Date(notif.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </span>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
};
