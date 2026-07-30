import { CopyOutlined, PlusOutlined } from '@ant-design/icons'
import { App, Button, Card, Col, Empty, Flex, Row, Statistic, Tag, Tooltip, Typography } from 'antd'
import { useEffect, useState } from 'react'
import { api, csrfHeaders, errorMessage } from '../api'
import { useAuth } from '../auth'
import { ResourceEditor } from '../components/ResourceEditor'
import { useNavigation } from '../routing'
import type { ResourceCardData, ResourceInput } from '../types'

export function OverviewPage() {
  const { message } = App.useApp()
  const { session } = useAuth()
  const { navigate } = useNavigation()
  const [resources, setResources] = useState<ResourceCardData[]>([])
  const [loading, setLoading] = useState(true)
  const [editorOpen, setEditorOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const { data } = await api.get<ResourceCardData[]>('/resources')
      setResources(data)
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [])

  const save = async (value: ResourceInput) => {
    if (!session) return
    setSubmitting(true)
    try {
      await api.post('/resources', value, { headers: csrfHeaders(session.csrf_token) })
      setEditorOpen(false)
      await load()
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setSubmitting(false)
    }
  }

  const copyToken = async (resource: ResourceCardData) => {
    try {
      await navigator.clipboard.writeText(resource.token)
      message.success('Token 已复制')
    } catch {
      message.error('Token 复制失败')
    }
  }

  return (
    <section>
      <Flex justify="space-between" align="center" className="page-heading">
        <div>
          <Typography.Title level={2}>算力资源</Typography.Title>
          <Typography.Text type="secondary">查看 GPU 容量与当前分配情况</Typography.Text>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setEditorOpen(true)}>新建算力资源</Button>
      </Flex>
      {!loading && resources.length === 0 ? <Empty description="尚未创建算力资源" /> : (
        <Row gutter={[20, 20]}>
          {resources.map((resource) => (
            <Col xs={24} lg={12} xl={8} key={resource.id}>
              <Card
                loading={loading}
                hoverable
                className="resource-card"
                onClick={() => navigate(`/resources/${resource.id}`)}
              >
                <Flex justify="space-between" align="start">
                  <div>
                    <Typography.Title level={4}>{resource.name}</Typography.Title>
                    <Typography.Text type="secondary">{resource.gpu_model}</Typography.Text>
                  </div>
                  <Flex align="center" gap={4}>
                    {resource.overallocated && <Tag color="error">超配</Tag>}
                    <Tooltip title="复制 Token">
                      <Button
                        type="text"
                        icon={<CopyOutlined />}
                        aria-label="复制 Token"
                        onClick={(event) => {
                          event.stopPropagation()
                          void copyToken(resource)
                        }}
                      />
                    </Tooltip>
                  </Flex>
                </Flex>
                <Row gutter={12} className="resource-stats">
                  <Col span={8}><Statistic title="总卡数" value={resource.gpu_count} /></Col>
                  <Col span={8}><Statistic title="已分配" value={resource.allocated_gpu_count} valueStyle={resource.overallocated ? { color: '#dc2626' } : undefined} /></Col>
                  <Col span={8}><Statistic title="未分配" value={resource.available_gpu_count} /></Col>
                </Row>
              </Card>
            </Col>
          ))}
        </Row>
      )}
      <ResourceEditor
        open={editorOpen}
        submitting={submitting}
        onCancel={() => setEditorOpen(false)}
        onSubmit={save}
      />
    </section>
  )
}
