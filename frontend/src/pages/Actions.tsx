import ActionFeed from '../components/ActionFeed'
import { Card } from '../components/ui'

export default function Actions() {
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Actions</h1>
      <Card>
        <ActionFeed showHidden />
      </Card>
    </div>
  )
}
