export interface Campaign {
  id: string
  name: string
  status: string
  turn_count: number
}

export interface CharacterState {
  id: string
  name: string
  class_name: string
  level: number
  hp: number
  max_hp: number
  ac: number
  spell_slots: Record<string, number>
  features: Record<string, unknown>
}

export interface TurnEntry {
  turn_id: string
  sequence_number: number
  character_id: string
  player_action: string
  narrative: string | null
}

export interface SessionState {
  campaign: Campaign
  characters: CharacterState[]
  scene: {
    location: string
    time_of_day: string
    description: string
    npcs: string[]
    threats: string[]
  }
  recent_turns: TurnEntry[]
}

// WebSocket events

export interface WsSessionStateEvent {
  event: 'session.state'
  payload: SessionState
}

export interface WsNarrativeStartEvent {
  event: 'turn.narrative_start'
  payload: { turn_id: string }
}

export interface WsNarrativeChunkEvent {
  event: 'turn.narrative_chunk'
  payload: { turn_id: string; chunk: string; sequence: number }
}

export interface WsNarrativeEndEvent {
  event: 'turn.narrative_end'
  payload: { turn_id: string; narrative: string }
}

export interface WsSystemErrorEvent {
  event: 'system.error'
  payload: { message: string }
}

export type WsEvent =
  | WsSessionStateEvent
  | WsNarrativeStartEvent
  | WsNarrativeChunkEvent
  | WsNarrativeEndEvent
  | WsSystemErrorEvent

export interface TurnSubmitResponse {
  turn_id: string
  sequence_number: number
}
