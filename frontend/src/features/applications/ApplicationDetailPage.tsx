/** Review complete application facts and permission-aware mutation dialogs. */
import { Fragment, useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useSession } from '../auth/SessionProvider';
import { applicationApi, applicationGroups, applicationLabels } from './applicationApi';
import { ApplicationForm } from './ApplicationForm';
import { Button } from '../../components/Button';
import { Modal } from '../../components/Modal';
import type { ApplicationDetail } from '../../types';
/** Resolve details from the backend and never infer hidden parent data. */
export default function ApplicationDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { user } = useSession();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<ApplicationDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const [editing, setEditing] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState('');
  const [notice, setNotice] = useState('');
  const inScope = detail && user && (user.portfolioAccess.includes(detail.portfolioId)
    || user.role === 'Administrator' && !user.portfolioAccess.length);
  const writable = inScope && user && ['Administrator', 'Portfolio Leader', 'Engineer'].includes(user.role);
  useEffect(() => { document.title = `${detail?.name ?? 'Application'} · KP ETSIP`; }, [detail]);
  useEffect(() => {
    let active = true;
    setLoading(true); setError(''); setDetail(null);
    applicationApi.detail(id ?? '').then((response) => { if (active) setDetail(response); })
      .catch((failure) => { if (active) setError(failure instanceof Error ? failure.message : 'Unable to load application'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [id, revision]);
  const remove = async () => {
    if (!detail) return;
    setDeleting(true); setDeleteError('');
    try { await applicationApi.delete(detail.id, detail.updatedAt); navigate('/applications'); }
    catch (failure) { setDeleteError(failure instanceof Error ? failure.message : 'Unable to delete application'); }
    finally { setDeleting(false); }
  };
  return (
    <section>
      <Link to="/applications">Back to applications</Link>
      {loading && <p role="status">Loading application…</p>}
      {error && (
        <div>
          <p role="alert" className="error-text">{error}</p>
          <Button variant="secondary" onClick={() => setRevision((value) => value + 1)}>Retry</Button>
        </div>
      )}
      <p role="status" aria-live="polite">{notice}</p>
      {detail && (
        <>
          <div className="page-heading">
            <h1>{detail.name}</h1>
            <div className="actions">
              {writable && <Button variant="secondary" onClick={() => setEditing(true)}>Edit application</Button>}
              {inScope && user?.role === 'Administrator' && <Button variant="secondary" onClick={() => {
                setRemoving(true); setDeleteError('');
              }}>Delete application</Button>}
            </div>
          </div>
          {applicationGroups.map((group) => (
            <section key={group.title}>
              <h2>{group.title}</h2>
              <dl className="identity-details">
                {group.keys.map((key) => (
                  <Fragment key={key}>
                    <dt>{applicationLabels[key]}</dt>
                    <dd>{key === 'portfolioId' ? (
                      <Link to={`/portfolios/${detail.portfolio.id}`}>{detail.portfolio.name}</Link>
                    ) : key === 'repositoryUrl' || key === 'pipelineUrl' ? (
                      detail[key] ? <a href={detail[key]!} target="_blank" rel="noreferrer">{detail[key]}</a> : 'Not provided'
                    ) : detail[key]}</dd>
                  </Fragment>
                ))}
              </dl>
            </section>
          ))}
          <dl className="identity-details">
            <dt>Application ID</dt>
            <dd>{detail.id}</dd>
            <dt>Created at</dt>
            <dd>{detail.createdAt}</dd>
            <dt>Updated at</dt>
            <dd>{detail.updatedAt}</dd>
            <dt>Portfolio product area</dt>
            <dd>{detail.portfolio.productArea}</dd>
            <dt>Portfolio status</dt>
            <dd>{detail.portfolio.status}</dd>
          </dl>
          {editing && (
            <Modal title="Edit application" onClose={() => setEditing(false)}>
              <ApplicationForm application={detail} onCancel={() => setEditing(false)} onSaved={() => {
                setEditing(false); setNotice('Application updated'); setRevision((value) => value + 1);
              }} />
            </Modal>
          )}
          {removing && (
            <Modal title="Delete application" onClose={() => { if (!deleting) setRemoving(false); }}>
              <p>Delete {detail.name}? This cannot be undone.</p>
              {deleteError && <p role="alert" className="error-text">{deleteError}</p>}
              <div className="actions">
                <Button variant="secondary" disabled={deleting} onClick={() => setRemoving(false)}>Cancel</Button>
                <Button loading={deleting} onClick={remove}>Confirm delete</Button>
              </div>
            </Modal>
          )}
        </>
      )}
    </section>
  );
}
