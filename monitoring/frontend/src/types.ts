export interface AdminSession {
  username: string
  full_name: string
  email: string
  email_verified: boolean
  role: 'admin' | 'user'
  csrf_token: string
}

export interface ResourceCardData {
  description: string
  id: string
  name: string
  gpu_model: string
  default_cpu_cores: number
  default_memory_gib: number
  gpu_count: number
  cpu_cores: number
  memory_gib: number
  allocated_gpu_count: number
  available_gpu_count: number
  reserved_gpu_count: number
  reserved_cpu_cores: number
  reserved_memory_gib: number
  remaining_gpu_count: number
  remaining_cpu_cores: number
  remaining_memory_gib: number
  overallocated: boolean
  status: 'active' | 'disabled'
  created_at?: string
}

export interface ResourceInput {
  description?: string
  name: string
  gpu_model: string
  default_cpu_cores: number
  default_memory_gib: number
  gpu_count: number
  cpu_cores: number
  memory_gib: number
}

export interface ContainerSummary {
  id: string
  name: string
  project_name: string
  applicant_name: string
  generation: number
  status: 'online' | 'offline'
  last_received_at: string
  expires_at: string | null
  allocated_gpu_count: number
  utilization_1h: number | null
  utilization_6h: number | null
  utilization_1d: number | null
  utilization_7d: number | null
}

export interface ChartPoint {
  time: string
  memory_used: number | null
  memory_total: number | null
  utilization: number | null
}

export interface GpuChartSeries {
  gpuid: string
  shared: boolean
  first_reported_at: string
  last_reported_at: string
  points: ChartPoint[]
}

export interface ChartResponse {
  container_id: string
  container_name: string
  project_name: string
  applicant_name: string
  range: ChartRange
  bucket_seconds: number
  window_start: string
  window_end: string
  instance_first_reported_at: string
  instance_removed_at: string | null
  series: GpuChartSeries[]
}

export type ChartRange = '1h' | '6h' | '1d' | '7d'

export interface UserData {
  id: string
  username: string
  full_name: string
  email: string
  email_verified_at: string | null
  role: 'admin' | 'user'
  status: 'active' | 'disabled'
  created_at: string
}

export interface RegistrationData {
  id: string
  username: string
  full_name: string
  email: string
  status: 'email_pending' | 'pending' | 'approved' | 'rejected'
  email_verified_at: string | null
  review_comment: string | null
  reviewed_at: string | null
  created_at: string
}

export interface SmtpSettingsData {
  host: string
  port: number
  username: string
  from_email: string
  from_name: string
  use_tls: boolean
  password_set: boolean
  source: 'database' | 'environment'
}

export interface SmtpSettingsInput {
  host: string
  port: number
  username: string
  password?: string
  from_email: string
  from_name: string
  use_tls: boolean
}

export interface GeneralSettingsData {
  api_base_url: string
  low_utilization_warning_enabled: boolean
  low_utilization_threshold: number
  source: 'database' | 'environment'
}

export interface GeneralSettingsInput {
  api_base_url: string
  low_utilization_warning_enabled: boolean
  low_utilization_threshold: number
}

export interface ProjectData {
  id: string
  name: string
  description: string
  status: 'active' | 'disabled'
  created_at: string
}

export interface ComputeRequestChangeData {
  id: string
  change_type: 'extend' | 'expand' | 'release' | 'cpu' | 'memory'
  amount: number
  approval_status: 'pending' | 'approved' | 'rejected'
  before_value: number
  after_value: number
  reviewer_name: string | null
  review_comment: string | null
  reviewed_at: string | null
  created_at: string
}

export interface ComputeRequestData {
  id: string
  applicant_id: string
  applicant_username: string
  applicant_name: string
  project_id: string
  project_name: string
  resource_id: string
  resource_name: string
  gpu_count: number
  cpu_cores: number
  memory_gib: number
  duration_days: number
  approval_status: 'pending' | 'approved' | 'rejected'
  runtime_status: 'not_started' | 'running' | 'expiring' | 'expired' | null
  actual_gpu_count: number
  over_quota: boolean
  reviewer_name: string | null
  review_comment: string | null
  reviewed_at: string | null
  token: string | null
  started_at: string | null
  expires_at: string | null
  created_at: string
  changes: ComputeRequestChangeData[]
}

export interface HistoryContainerData {
  id: string
  name: string
  generation: number
  status: 'online' | 'offline' | 'removed'
  applicant_id: string
  applicant_name: string
  project_id: string
  project_name: string
  resource_id: string
  resource_name: string
  compute_request_id: string
  first_reported_at: string
  last_received_at: string
  removed_at: string | null
  expires_at: string | null
  usage_summary_status: 'pending' | 'completed' | null
  usage_duration_seconds: number | null
  usage_gpu_count: number | null
  usage_gpu_utilization_avg: number | null
  usage_gpu_utilization_max: number | null
  usage_memory_utilization_avg: number | null
  usage_memory_utilization_max: number | null
}

export interface HourlyHistoryPoint {
  time: string
  utilization_avg: number
  utilization_max: number
  memory_used_avg: number
  memory_used_max: number
  memory_total: number
  online_seconds: number
  sample_count: number
}

export interface HistoryContainerChartData {
  container_id: string
  container_name: string
  project_name: string
  applicant_name: string
  first_reported_at: string
  removed_at: string
  series: Array<{ gpuid: string; points: HourlyHistoryPoint[] }>
}
