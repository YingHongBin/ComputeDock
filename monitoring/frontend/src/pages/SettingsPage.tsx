import { Alert, App, Button, Card, Form, Input, InputNumber, Space, Switch, Tag, Typography } from 'antd'
import { useEffect, useState } from 'react'
import { api, csrfHeaders, errorMessage } from '../api'
import { useAuth } from '../auth'
import type { SmtpSettingsData, SmtpSettingsInput } from '../types'

type SmtpFormValues = SmtpSettingsInput & { password?: string }

function payloadFrom(values: SmtpFormValues): SmtpSettingsInput {
  const payload = { ...values }
  if (!payload.password) delete payload.password
  return payload
}

export function SettingsPage() {
  const { session } = useAuth()
  const { message } = App.useApp()
  const [form] = Form.useForm<SmtpFormValues>()
  const [settings, setSettings] = useState<SmtpSettingsData | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const { data } = await api.get<SmtpSettingsData>('/settings/smtp')
      setSettings(data)
      form.setFieldsValue({
        host: data.host,
        port: data.port,
        username: data.username,
        password: undefined,
        from_email: data.from_email,
        from_name: data.from_name,
        use_tls: data.use_tls,
      })
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [])

  const save = async (values: SmtpFormValues) => {
    if (!session) return
    setSaving(true)
    try {
      const { data } = await api.put<SmtpSettingsData>('/settings/smtp', payloadFrom(values), {
        headers: csrfHeaders(session.csrf_token),
      })
      setSettings(data)
      form.setFieldValue('password', undefined)
      message.success('SMTP 设置已保存')
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setSaving(false)
    }
  }

  const testEmail = async () => {
    if (!session) return
    setTesting(true)
    try {
      const values = await form.validateFields()
      const { data } = await api.post<{ recipient: string }>(
        '/settings/smtp/test',
        payloadFrom(values),
        { headers: csrfHeaders(session.csrf_token) },
      )
      message.success(`测试邮件已发送至 ${data.recipient}`)
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setTesting(false)
    }
  }

  return (
    <section>
      <div className="page-heading">
        <Typography.Title level={2}>设置</Typography.Title>
        <Typography.Text type="secondary">管理系统邮件发送配置。</Typography.Text>
      </div>
      <Card
        title={<Space>SMTP 设置 {settings && <Tag>{settings.source === 'database' ? '数据库配置' : '环境变量配置'}</Tag>}</Space>}
        loading={loading}
      >
        <Alert
          type="info"
          showIcon
          message="发送测试邮件会使用当前表单内容，并发送到当前管理员绑定的邮箱。"
          className="settings-alert"
        />
        <Form<SmtpFormValues>
          form={form}
          layout="vertical"
          onFinish={save}
          initialValues={{ port: 587, from_name: 'ComputeDock', use_tls: true }}
          className="settings-form"
        >
          <Form.Item name="host" label="SMTP Host" rules={[{ required: true, whitespace: true }]}>
            <Input maxLength={255} placeholder="smtp.example.com" />
          </Form.Item>
          <Form.Item name="port" label="SMTP Port" rules={[{ required: true }]}>
            <InputNumber min={1} max={65535} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="username" label="SMTP Username">
            <Input maxLength={320} autoComplete="username" />
          </Form.Item>
          <Form.Item
            name="password"
            label="SMTP Password"
            extra={settings?.password_set ? '密码已设置；留空将保留现有密码。' : '当前未设置密码。'}
          >
            <Input.Password maxLength={1024} autoComplete="new-password" />
          </Form.Item>
          <Form.Item name="from_email" label="From Email" rules={[{ required: true }, { type: 'email' }]}>
            <Input maxLength={320} placeholder="computedock@example.com" />
          </Form.Item>
          <Form.Item name="from_name" label="From Name">
            <Input maxLength={200} placeholder="ComputeDock" />
          </Form.Item>
          <Form.Item name="use_tls" label="Use TLS" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Space>
            <Button type="primary" htmlType="submit" loading={saving}>保存</Button>
            <Button onClick={() => void testEmail()} loading={testing}>发送测试邮件</Button>
          </Space>
        </Form>
      </Card>
    </section>
  )
}
