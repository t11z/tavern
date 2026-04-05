// ---------------------------------------------------------------------------
// API response types
// ---------------------------------------------------------------------------

export interface Campaign {
  id: string
  name: string
  status: string
  created_at: string
  last_played_at: string | null
}

export interface CampaignState {
  rolling_summary: string
  scene_context: string
  world_state: Record<string, unknown>
  turn_count: number
  updated_at: string
}

export interface CampaignDetail extends Campaign {
  world_seed: string | null
  dm_persona: string | null
  state: CampaignState | null
}

export interface CharacterSummary {
  id: string
  campaign_id: string
  name: string
  class_name: string
  level: number
  hp: number
  max_hp: number
  ac: number
  ability_scores: Record<string, number>
  spell_slots: Record<string, number>
  features: Record<string, unknown>
}

// ---------------------------------------------------------------------------
// In-session state
// ---------------------------------------------------------------------------

export interface InventoryItem {
  id?: string
  name: string
  damage?: string
  ac_bonus?: number
  quantity?: number
}

export interface SpellEntry {
  name: string
  level: number
  school?: string
  damage?: string
}

export interface CharacterState {
  id: string
  name: string
  species?: string
  class_name: string
  level: number
  hp: number
  max_hp: number
  ac: number
  speed?: number
  initiative_modifier?: number
  proficiency_bonus?: number
  hit_die?: string
  ability_scores?: Record<string, number>
  ability_modifiers?: Record<string, number>
  proficiencies?: string[]
  languages?: string[]
  background?: string
  spell_slots: Record<string, number>
  spell_slots_max?: Record<string, number>
  spells?: SpellEntry[]
  features: Record<string, unknown>
  class_features?: Record<string, string>
  inventory?: InventoryItem[]
  conditions?: string[]
}

export interface MechanicalResultEntry {
  type:
    | 'attack_roll'
    | 'saving_throw'
    | 'ability_check'
    | 'damage'
    | 'healing'
    | 'condition_applied'
    | 'condition_removed'
    | 'spell_cast'
    | 'resource_consumed'
    | 'reaction_used'
    | 'initiative_rolled'
    | 'rest_result'
    | 'combat_started'
    | 'combat_ended'
  [key: string]: unknown
}

export interface TurnMechanicalGroup {
  turn_id: string
  sequence_number: number
  character_name: string
  entries: MechanicalResultEntry[]
  created_at: string
}

export interface TurnEntry {
  turn_id: string
  sequence_number: number
  character_id: string
  character_name?: string
  player_action: string
  rules_result: string | null
  narrative: string | null
  mechanical_results?: MechanicalResultEntry[] | null
  created_at?: string
}

export interface SessionScene {
  location: string
  time_of_day: string
  environment: string
  description: string
  npcs: string[]
  threats: string[]
}

export interface SessionState {
  campaign: {
    id: string
    name: string
    status: string
    turn_count: number
  }
  characters: CharacterState[]
  scene: SessionScene
  recent_turns: TurnEntry[]
  combat: { initiative_order: InitiativeEntry[]; surprised: string[] } | null
}

// ---------------------------------------------------------------------------
// WebSocket events
// ---------------------------------------------------------------------------

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
  payload: {
    turn_id: string
    narrative: string
    mechanical_results: MechanicalResultEntry[] | null
    character_updates: unknown[]
    sequence_number?: number
    character_name?: string
    created_at?: string
  }
}

export interface WsSystemErrorEvent {
  event: 'system.error'
  payload: { message: string }
}

export interface WsCharacterUpdatedEvent {
  event: 'character.updated'
  payload: {
    character_id: string
    campaign_id: string
    hp: number
    spell_slots: Record<string, number>
  }
}

export interface InitiativeEntry {
  character_id: string
  participant_type: string
  initiative_result: number
  surprised: boolean
}

export interface WsCombatStartedEvent {
  event: 'combat.started'
  payload: {
    initiative_order: InitiativeEntry[]
    surprised: string[]
  }
}

export interface WsCombatEndedEvent {
  event: 'combat.ended'
  payload: Record<string, never>
}

export interface WsSuggestedActionsEvent {
  event: 'turn.suggested_actions'
  payload: {
    turn_id: string
    suggestions: string[]
  }
}

export type WsEvent =
  | WsSessionStateEvent
  | WsNarrativeStartEvent
  | WsNarrativeChunkEvent
  | WsNarrativeEndEvent
  | WsSystemErrorEvent
  | WsCharacterUpdatedEvent
  | WsCombatStartedEvent
  | WsCombatEndedEvent
  | WsSuggestedActionsEvent

// ---------------------------------------------------------------------------
// API request/response shapes
// ---------------------------------------------------------------------------

export interface TurnSubmitResponse {
  turn_id: string
  sequence_number: number
}
