import { Link } from "react-router-dom";
import { Compass } from "lucide-react";
import { Button, Card, EmptyState } from "../ui";

export function NotFoundPage() {
  return (
    <div className="mx-auto max-w-2xl py-16">
      <Card>
        <EmptyState
          icon={<Compass className="h-5 w-5" />}
          title="页面不存在"
          description="链接可能已失效，或项目已被归档。"
          action={
            <Link to="/">
              <Button variant="primary">返回仪表盘</Button>
            </Link>
          }
        />
      </Card>
    </div>
  );
}
