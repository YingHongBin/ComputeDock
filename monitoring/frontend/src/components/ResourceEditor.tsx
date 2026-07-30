import { Form, Input, InputNumber, Modal } from 'antd'
import { useEffect } from 'react'
import type { ResourceCardData, ResourceInput } from '../types'

interface Props {
  open: boolean
  resource?: ResourceCardData | null
  submitting: boolean
  onCancel: () => void
  onSubmit: (value: ResourceInput) => Promise<void>
}

export function ResourceEditor({ open, resource, submitting, onCancel, onSubmit }: Props) {
  const [form] = Form.useForm<ResourceInput>()

  useEffect(() => {
    if (!open) return
    if (resource) {
      form.setFieldsValue({
        name: resource.name,
        gpu_model: resource.gpu_model,
        gpu_count: resource.gpu_count,
      })
    } else {
      form.resetFields()
    }
  }, [form, open, resource])

  return (
    <Modal
      title={resource ? '编辑算力资源' : '新建算力资源'}
      open={open}
      confirmLoading={submitting}
      onCancel={onCancel}
      onOk={() => form.validateFields().then(onSubmit)}
      okText="保存"
      cancelText="取消"
      destroyOnHidden
    >
      <Form form={form} layout="vertical" requiredMark={false}>
        <Form.Item name="name" label="资源名称" rules={[{ required: true, whitespace: true }]}>
          <Input maxLength={200} placeholder="例如：A100 训练集群" />
        </Form.Item>
        <Form.Item name="gpu_model" label="GPU 型号" rules={[{ required: true, whitespace: true }]}>
          <Input maxLength={200} placeholder="例如：NVIDIA A100 80GB" />
        </Form.Item>
        <Form.Item name="gpu_count" label="GPU 总卡数" rules={[{ required: true }]}>
          <InputNumber min={1} max={10000} precision={0} className="full-width" />
        </Form.Item>
      </Form>
    </Modal>
  )
}

