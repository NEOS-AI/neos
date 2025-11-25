import { User } from "lucide-react";

interface MessageAvatarProps {
  isUser: boolean;
}

/**
 * MessageAvatar Component
 * Modern avatar design with elegant gradients and shadows
 */
export default function MessageAvatar({ isUser }: MessageAvatarProps) {
  if (isUser) {
    return (
      <div className="w-9 h-9 rounded-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center shadow-md ring-2 ring-blue-500/20 transition-transform hover:scale-105">
        <User size={18} className="text-white" />
      </div>
    );
  }

  return (
    <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-blue-700 via-slate-800 to-indigo-800 flex items-center justify-center text-white font-bold text-base shadow-md ring-2 ring-blue-700/20 transition-transform hover:scale-105">
      N
    </div>
  );
}
