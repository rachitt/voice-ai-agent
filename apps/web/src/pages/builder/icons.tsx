import {
  MessageSquare,
  ClipboardList,
  Cable,
  GitBranch,
  PhoneForwarded,
  Voicemail,
  PhoneOff,
  Sheet,
  Cloud,
  BookOpen,
  type LucideIcon,
} from 'lucide-react'
import type { StepKind } from './types'

export const KIND_ICON: Record<StepKind | 'sheets' | 'salesforce', LucideIcon> = {
  greeting: MessageSquare,
  collect: ClipboardList,
  api: Cable,
  condition: GitBranch,
  transfer: PhoneForwarded,
  voicemail: Voicemail,
  kb_lookup: BookOpen,
  end: PhoneOff,
  sheets: Sheet,
  salesforce: Cloud,
}

export const KIND_TINT: Record<StepKind, string> = {
  greeting: 'text-accent',
  collect: 'text-sky-300',
  api: 'text-violet-300',
  condition: 'text-warn',
  transfer: 'text-orange-300',
  voicemail: 'text-pink-300',
  kb_lookup: 'text-emerald-300',
  end: 'text-danger',
}
