import { useNavigate } from 'react-router-dom'
import AdminRefImagePage from '../../components/admin/refImage/AdminRefImagePage'

/** /admin/reference — 레퍼런스 이미지 관리 (기존 AdminRefImagePage 라우트 wrapper). */
export default function AdminReferencePage() {
  const navigate = useNavigate()
  return <AdminRefImagePage onBack={() => navigate('/admin')} />
}
