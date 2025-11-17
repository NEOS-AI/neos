import { User } from "lucide-react";

interface MessageAvatarProps {
  isUser: boolean;
}

/**
 * MessageAvatar Component
 * Displays the avatar for user or assistant messages
 */
export default function MessageAvatar({ isUser }: MessageAvatarProps) {
  if (isUser) {
    return (
      <div className="w-7 h-7 rounded-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center">
        <User size={16} className="text-white" />
      </div>
    );
  }

  return (
    <div className="w-7 h-7 rounded-md bg-gradient-to-br from-orange-400 to-amber-600 flex items-center justify-center text-white font-bold text-sm">
      N
    </div>
  );
}
