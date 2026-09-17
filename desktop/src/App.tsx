import { HomeScreen } from './screens/HomeScreen'
import { LaunchScreen } from './screens/LaunchScreen'
import { SettingsScreen } from './screens/SettingsScreen'
import { WorkspaceScreen } from './screens/WorkspaceScreen'
import { usePoStore } from './store'

export default function App() {
  const screen = usePoStore((s) => s.screen)

  return (
    <div className="h-full w-full text-white">
      {screen === 'launch' ? <LaunchScreen /> : null}
      {screen === 'home' ? <HomeScreen /> : null}
      {screen === 'workspace' ? <WorkspaceScreen /> : null}
      {screen === 'settings' ? <SettingsScreen /> : null}
    </div>
  )
}
