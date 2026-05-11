import type { PaletteItem } from './types'

export const PALETTE: PaletteItem[] = [
  { kind: 'greeting', group: 'core', title: 'Greeting', subtitle: 'Opening line + tone' },
  { kind: 'collect', group: 'core', title: 'Collect Info', subtitle: 'Gather caller fields' },
  { kind: 'api', group: 'core', title: 'API Call', subtitle: 'Outbound webhook' },
  { kind: 'condition', group: 'core', title: 'Condition', subtitle: 'Branch on values' },
  { kind: 'transfer', group: 'core', title: 'Transfer', subtitle: 'Hand off to human' },
  { kind: 'voicemail', group: 'core', title: 'Voicemail', subtitle: 'Leave a message' },
  { kind: 'end', group: 'core', title: 'End Call', subtitle: 'Hang up gracefully' },
  { kind: 'sheets', group: 'integrations', title: 'Google Sheets', subtitle: 'Append a row' },
  { kind: 'salesforce', group: 'integrations', title: 'Salesforce', subtitle: 'Upsert lead' },
]
