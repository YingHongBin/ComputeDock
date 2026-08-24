import { EditOutlined, PlusOutlined } from '@ant-design/icons'
import { App, Button, Card, Flex, Form, Input, Modal, Select, Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useEffect, useState } from 'react'
import { api, csrfHeaders, errorMessage } from '../api'
import { useAuth } from '../auth'
import type { ProjectData, UserData } from '../types'

export function ProjectsPage() {
  const { session } = useAuth()
  const { message } = App.useApp()
  const [projects, setProjects] = useState<ProjectData[]>([])
  const [users, setUsers] = useState<UserData[]>([])
  const [editing, setEditing] = useState<ProjectData | null | undefined>(undefined)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [form] = Form.useForm()

  const load = async () => {
    setLoading(true)
    try {
      const [projectResponse, userResponse] = await Promise.all([
        api.get<ProjectData[]>('/projects', { params: { include_disabled: true } }),
        api.get<UserData[]>('/users'),
      ])
      setProjects(projectResponse.data)
      setUsers(userResponse.data)
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [])

  const openEditor = (project: ProjectData | null) => {
    setEditing(project)
    if (project) {
      form.setFieldsValue({
        name: project.name,
        description: project.description,
        member_ids: project.members.map((member) => member.id),
      })
    } else form.resetFields()
  }

  const save = async (values: Record<string, unknown>) => {
    if (!session) return
    setBusy(true)
    try {
      if (editing) await api.put(`/projects/${editing.id}`, values, { headers: csrfHeaders(session.csrf_token) })
      else await api.post('/projects', values, { headers: csrfHeaders(session.csrf_token) })
      message.success(editing ? 'Squad已更新' : 'Squad已创建')
      setEditing(undefined)
      await load()
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  const toggle = async (project: ProjectData) => {
    if (!session) return
    try {
      const action = project.status === 'active' ? 'disable' : 'enable'
      await api.post(`/projects/${project.id}/${action}`, undefined, { headers: csrfHeaders(session.csrf_token) })
      message.success(project.status === 'active' ? 'Squad已禁用' : 'Squad已启用')
      await load()
    } catch (error) {
      message.error(errorMessage(error))
    }
  }

  const columns: ColumnsType<ProjectData> = [
    { title: 'Squad名称', dataIndex: 'name', width: 180 },
    { title: '说明', dataIndex: 'description', render: (value) => value || '--' },
    { title: '成员', dataIndex: 'members', render: (members: ProjectData['members']) => <Space wrap>{members.length ? members.map((member) => <Tag key={member.id}>{member.full_name}</Tag>) : <Typography.Text type="secondary">暂无成员</Typography.Text>}</Space> },
    { title: '状态', dataIndex: 'status', width: 90, render: (value) => value === 'active' ? <Tag color="success">正常</Tag> : <Tag>已禁用</Tag> },
    { title: '操作', width: 170, render: (_, row) => <Space><Button size="small" icon={<EditOutlined />} onClick={() => openEditor(row)}>编辑</Button><Button size="small" onClick={() => void toggle(row)}>{row.status === 'active' ? '禁用' : '启用'}</Button></Space> },
  ]

  return (
    <section>
      <Flex justify="space-between" align="center" className="page-heading">
        <div>
          <Typography.Title level={2}>Squad管理</Typography.Title>
          <Typography.Text type="secondary">创建Squad并明确维护Squad成员。</Typography.Text>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => openEditor(null)}>新建Squad</Button>
      </Flex>
      <Card><Table rowKey="id" loading={loading} columns={columns} dataSource={projects} scroll={{ x: 900 }} /></Card>
      <Modal title={editing ? '编辑Squad' : '新建Squad'} open={editing !== undefined} onCancel={() => setEditing(undefined)} onOk={() => form.submit()} confirmLoading={busy} destroyOnHidden>
        <Form form={form} layout="vertical" onFinish={save} preserve={false}>
          <Form.Item name="name" label="Squad名称" rules={[{ required: true, whitespace: true }]}><Input maxLength={200} /></Form.Item>
          <Form.Item name="description" label="说明"><Input.TextArea rows={3} maxLength={4000} /></Form.Item>
          <Form.Item name="member_ids" label="Squad成员" initialValue={[]}>
            <Select mode="multiple" showSearch optionFilterProp="label" options={users.filter((user) => user.status === 'active').map((user) => ({ value: user.id, label: `${user.full_name} (${user.username})` }))} />
          </Form.Item>
        </Form>
      </Modal>
    </section>
  )
}
