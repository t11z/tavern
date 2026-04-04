import { useState } from 'react'
import './index.css'
import { CampaignList } from './components/CampaignList'
import { CampaignDetailView } from './components/CampaignDetail'
import { CharacterCreation } from './components/CharacterCreation'
import { GameSession } from './components/GameSession'

type View =
  | { screen: 'campaigns' }
  | { screen: 'campaign'; campaignId: string }
  | { screen: 'create-character'; campaignId: string }
  | { screen: 'session'; campaignId: string }

export default function App() {
  const [view, setView] = useState<View>({ screen: 'campaigns' })

  switch (view.screen) {
    case 'campaigns':
      return (
        <CampaignList
          onSelect={(id) => setView({ screen: 'campaign', campaignId: id })}
        />
      )

    case 'campaign':
      return (
        <CampaignDetailView
          campaignId={view.campaignId}
          onCreateChar={() =>
            setView({ screen: 'create-character', campaignId: view.campaignId })
          }
          onStartSession={() =>
            setView({ screen: 'session', campaignId: view.campaignId })
          }
          onBack={() => setView({ screen: 'campaigns' })}
        />
      )

    case 'create-character':
      return (
        <CharacterCreation
          campaignId={view.campaignId}
          onDone={() => setView({ screen: 'campaign', campaignId: view.campaignId })}
          onCancel={() => setView({ screen: 'campaign', campaignId: view.campaignId })}
        />
      )

    case 'session':
      return (
        <GameSession
          campaignId={view.campaignId}
          onEndSession={() => setView({ screen: 'campaign', campaignId: view.campaignId })}
        />
      )
  }
}
