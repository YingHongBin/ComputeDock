import { CopyOutlined, DeleteOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons'
import { App, Button, Card, Col, Empty, Flex, Row, Space, Statistic, Tag, Typography } from 'antd'
import { useEffect, useState } from 'react'
import { api, csrfHeaders, errorMessage } from '../api'
import { useAuth } from '../auth'
import { ResourceEditor } from '../components/ResourceEditor'
import { useNavigation } from '../routing'
import type { ResourceCardData, ResourceInput } from '../types'

export function OverviewPage() {
  const { message, modal } = App.useApp()
  const { session } = useAuth()
  const { navigate } = useNavigation()
  const [resources, setResources] = useState<ResourceCardData[]>([])
  const [loading, setLoading] = useState(true)
  const [editorOpen, setEditorOpen] = useState(false)
  const [editing, setEditing] = useState<ResourceCardData | null>(null)
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
      if (editing) {
        await api.put(`/resources/${editing.id}`, value, { headers: csrfHeaders(session.csrf_token) })
      } else {
        await api.post('/resources', value, { headers: csrfHeaders(session.csrf_token) })
      }
      setEditorOpen(false)
      setEditing(null)
      await load()
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setSubmitting(false)
    }
  }

  const remove = (resource: ResourceCardData) => {
    if (!session) return
    modal.confirm({
      title: `删除算力资源“${resource.name}”？`,
      content: '删除后 Token 永久失效，页面不提供恢复入口。',
      okText: '确认删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        await api.delete(`/resources/${resource.id}`, { headers: csrfHeaders(session.csrf_token) })
        await load()
      },
    })
  }

  return (
    <section>
      <Flex justify="space-between" align="center" className="page-heading">
        <div>
          <Typography.Title level={2}>算力资源</Typography.Title>
          <Typography.Text type="secondary">查看 GPU 容量与当前分配情况</Typography.Text>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); setEditorOpen(true) }}>新建算力资源</Button>
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
                actions={[
                  <EditOutlined key="edit" onClick={(event) => { event.stopPropagation(); setEditing(resource); setEditorOpen(true) }} />,
                  <DeleteOutlined key="delete" onClick={(event) => { event.stopPropagation(); remove(resource) }} />,
                ]}
              >
                <Flex justify="space-between" align="start">
                  <div>
                    <Typography.Title level={4}>{resource.name}</Typography.Title>
                    <Typography.Text type="secondary">{resource.gpu_model}</Typography.Text>
                  </div>
                  {resource.overallocated && <Tag color="error">超配</Tag>}
                </Flex>
                <Row gutter={12} className="resource-stats">
                  <Col span={8}><Statistic title="总卡数" value={resource.gpu_count} /></Col>
                  <Col span={8}><Statistic title="已分配" value={resource.allocated_gpu_count} valueStyle={resource.overallocated ? { color: '#dc2626' } : undefined} /></Col>
                  <Col span={8}><Statistic title="未分配" value={resource.available_gpu_count} /></Col>
                </Row>
                <div className="token-box" onClick={(event) => event.stopPropagation()}>
                  <Typography.Text className="token-text" copyable={{ text: resource.token, icon: <CopyOutlined /> }}>{resource.token}</Typography.Text>
                </div>
              </Card>
            </Col>
          ))}
        </Row>
      )}
      <ResourceEditor
        open={editorOpen}
        resource={editing}
        submitting={submitting}
        onCancel={() => { setEditorOpen(false); setEditing(null) }}
        onSubmit={save}
      />
    </section>
  )
}
