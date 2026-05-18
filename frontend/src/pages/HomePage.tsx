import { Fragment, useRef, useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowRight, Box as BoxIcon, Download, FileUp, ScanSearch } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { API_BASE } from '../lib/axiosClient';


function BorderFlash({ children, className = '', delay = 0, flashClass = 'bg-flash' }: { children: React.ReactNode; className?: string; delay?: number; flashClass?: string }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setTimeout(() => {
            el.classList.remove(flashClass);
            void el.offsetWidth;
            el.classList.add(flashClass);
          }, delay);
        }
      },
      { threshold: 0.2 }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [delay, flashClass]);

  return <div ref={ref} className={className}>{children}</div>;
}


function FadeIn({ children, delay = 0, className = '' }: { children: React.ReactNode; delay?: number; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      ([entry]) => { setVisible(entry.isIntersecting); },
      { threshold: 0.1 }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return (
    <div
      ref={ref}
      className={className}
      style={{
        opacity: visible ? 1 : 0,
        transform: visible ? 'translateY(0)' : 'translateY(24px)',
        transition: `opacity 0.55s ease ${delay}ms, transform 0.55s ease ${delay}ms`,
      }}
    >
      {children}
    </div>
  );
}

export default function HomePage() {
  const navigate = useNavigate();
  const { currentUser, login } = useAuth();

  useEffect(() => { window.scrollTo(0, 0); }, []);

  const handleStart = () => {
    if (!currentUser) { navigate('/login'); return; }
    navigate('/project');
  };

  const handleDevLogin = async () => {
    try {
      const res = await fetch(`${API_BASE}/auth/dev-login`, {
        method: 'POST',
        credentials: 'include',
      });
      if (!res.ok) throw new Error(`dev-login failed: ${res.status}`);
      const user = await res.json();
      login(user);
    } catch (e) {
      console.error('[dev-login] 실패', e);
    }
  };

  return (
    <main className="flex-1 flex flex-col">

      {/* ── Hero (영상 배경) ── */}
      <section className="relative flex-1 flex flex-col items-center justify-center px-6 py-20 text-center overflow-hidden min-h-screen">
        <video
          src="/landing_demo.mp4"
          autoPlay muted loop playsInline
          className="absolute inset-0 w-full h-full object-cover opacity-55"
        />
        <div className="absolute inset-0 bg-gradient-to-b from-black/30 via-black/10 to-black/40" />
        <div className="relative z-10 flex flex-col items-center">
          <h1 className="text-3xl md:text-[2.75rem] font-semibold tracking-tight mb-5 drop-shadow-xl animated-gradient-text" style={{ lineHeight: '1.25' }}>
            도면 한 장으로<br />공간 배치를 완성하세요
          </h1>
          <p className="text-sm text-white/90 max-w-xl mb-8 leading-relaxed drop-shadow-lg">
            브랜드 매뉴얼과 도면만 업로드하면<br />
            집기 배치 동선 설계 GLB 다운로드까지 자동으로 완성됩니다
          </p>
          <button
            onClick={handleStart}
            className="flex items-center gap-2 bg-primary text-white font-bold rounded-xl px-7 py-3.5 text-sm hover:bg-primary/90 transition-colors shadow-lg"
          >
            지금 바로 시작하기 <ArrowRight size={16} />
          </button>
        </div>
      </section>

      <div className="h-px bg-gradient-to-r from-transparent via-white/10 to-transparent mx-8" />

      {/* ── 고민 카드 ── */}
      <section className="px-6 py-14">
        <div className="max-w-6xl mx-auto">
          <h2 className="text-2xl font-bold text-text-main text-center mb-3">혹시 이런 고민 있으신가요?</h2>
          <p className="text-sm text-slate-400 text-center mb-10">VMD 담당자라면 한 번쯤 겪어봤을 반복 작업들</p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {[
              { before: '집기 위치 잡는데\n반나절', after: '도면 업로드 후\n자동 배치', text: '집기 배치에 쏟는 단순 반복 업무, AI에게 맡기고 기획에 집중하세요' },
              { before: '브랜드마다\n처음부터 다시', after: '매뉴얼 업로드로\n자동 커스텀', text: '브랜드별 커스텀 배치를 자동 제안받아, 시안 제작의 피로도를 낮추세요' },
              { before: '기획 → 렌더링\n여러 툴 오가며', after: '업로드 한 번으로\n3D까지', text: '기획안부터 최종 시뮬레이션까지, VMD 워크플로우를 하나로 연결합니다' },
            ].map(({ before, after, text }, i) => (
              <BorderFlash key={i} delay={i * 700} className="bg-white/3 border border-white/10 rounded-2xl p-7">
                <div className="flex items-center gap-3 mb-6">
                  <div className="flex-1 rounded-xl bg-white/5 px-4 py-4 text-center" style={{ border: '1px solid rgba(255,255,255,0.06)' }}>
                    <p className="text-[11px] text-slate-500 mb-2 font-medium">기존</p>
                    <p className="text-sm text-slate-400 leading-relaxed whitespace-pre-line">{before}</p>
                  </div>
                  <ArrowRight size={20} className="text-primary flex-shrink-0" />
                  <div className="flex-1 rounded-xl bg-primary/15 px-4 py-4 text-center" style={{ border: '1.5px solid rgba(99,102,241,0.7)' }}>
                    <p className="text-[11px] text-primary/80 mb-2 font-medium">LandUP</p>
                    <p className="text-sm text-white font-semibold leading-relaxed whitespace-pre-line">{after}</p>
                  </div>
                </div>
                <p className="text-sm text-slate-300 leading-relaxed">{text}</p>
              </BorderFlash>
            ))}
          </div>
        </div>
      </section>

      <div className="h-px bg-gradient-to-r from-transparent via-white/10 to-transparent mx-8" />

      {/* ── 후기 ── */}
      <section className="px-6 py-16">
        <div className="max-w-5xl mx-auto">
          <h2 className="text-2xl font-bold text-text-main text-center mb-3">VMD 담당자들의 이야기</h2>
          <p className="text-sm text-slate-400 text-center mb-16">팝업 현장에서 직접 겪은 반복 업무, 이제는 달라집니다</p>

          {/* Row 1 — 2컬럼 */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-10 mb-14">
            {[
              { quote: '매번 새 팝업마다 집기 배치를 처음부터 손으로 잡았어요. 업로드 한 번으로 초안이 나오니까 그 시간을 기획에 쓸 수 있게 됐습니다.', name: '이*수', role: '여성 컨템포러리 패션 브랜드 VMD 담당 · 2년차', initials: '이' },
              { quote: '도면 받으면 AutoCAD 켜서 집기 하나하나 올리는 게 일이었는데, 이제 초안이 바로 나오니 수정만 하면 돼요.', name: '김*현', role: '국내 중견 뷰티 브랜드 마케팅팀 · 팝업 기획 5년차', initials: '김' },
            ].map(({ quote, name, role, initials }, i) => (
              <FadeIn key={name} delay={i * 150} className="flex flex-col items-center">
                <div className="bg-white/[0.04] rounded-3xl px-7 py-6 text-center w-full">
                  <p className="text-sm text-slate-300 leading-relaxed">"{quote}"</p>
                </div>
                <div className="flex items-center gap-2.5 mt-7">
                  <div className="w-7 h-7 rounded-full bg-primary/20 flex items-center justify-center text-xs text-primary font-semibold flex-shrink-0">{initials}</div>
                  <div className="text-left">
                    <p className="text-sm font-medium text-text-main">{name}</p>
                    <p className="text-xs text-slate-500">{role}</p>
                  </div>
                </div>
              </FadeIn>
            ))}
          </div>

          {/* Row 2 — 중앙 큰 인용구 */}
          <FadeIn delay={100} className="flex flex-col items-center mb-14">
            <div className="bg-white/[0.04] rounded-3xl px-10 py-8 text-center max-w-2xl w-full">
              <p className="text-sm md:text-base text-slate-200 leading-relaxed">
                "브랜드 매뉴얼대로 배치를 맞추는 게 제일 힘들었는데, LandUP이 자동으로 제안해줘서 수정만 하면 되더라고요. 클라이언트한테 3D로 바로 보여줄 수 있는 것도 큰 장점이에요."
              </p>
            </div>
            <div className="flex items-center gap-2.5 mt-6">
              <div className="w-7 h-7 rounded-full bg-primary/20 flex items-center justify-center text-xs text-primary font-semibold flex-shrink-0">박</div>
              <div className="text-left">
                <p className="text-sm font-medium text-text-main">박*영</p>
                <p className="text-xs text-slate-500">공간 디자인 스튜디오 · 브랜드 VMD 디렉터 8년차</p>
              </div>
            </div>
          </FadeIn>

          {/* Row 3 — 2컬럼 */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-10">
            {[
              { quote: 'GLB로 바로 내보낼 수 있어서 SketchUp에 올려보는 게 신기했어요. 시뮬레이션을 그 자리에서 보여주니 클라이언트 반응이 달라지더라고요.', name: '최*준', role: '라이프스타일 편집숍 전문 프리랜서 · 공간 디자인 3년차', initials: '최' },
              { quote: '팝업 시즌마다 같은 작업을 반복하는 게 너무 지쳐있었는데, AI가 배치 초안을 잡아주니까 훨씬 여유가 생겼어요.', name: '정*아', role: '스트리트 캐주얼 브랜드 리테일팀 VMD 팀장 · 7년차', initials: '정' },
            ].map(({ quote, name, role, initials }, i) => (
              <FadeIn key={name} delay={i * 150} className="flex flex-col items-center">
                <div className="bg-white/[0.04] rounded-3xl px-7 py-6 text-center w-full">
                  <p className="text-sm text-slate-300 leading-relaxed">"{quote}"</p>
                </div>
                <div className="flex items-center gap-2.5 mt-7">
                  <div className="w-7 h-7 rounded-full bg-primary/20 flex items-center justify-center text-xs text-primary font-semibold flex-shrink-0">{initials}</div>
                  <div className="text-left">
                    <p className="text-sm font-medium text-text-main">{name}</p>
                    <p className="text-xs text-slate-500">{role}</p>
                  </div>
                </div>
              </FadeIn>
            ))}
          </div>
        </div>
      </section>

      <div className="h-px bg-gradient-to-r from-transparent via-white/10 to-transparent mx-8" />

      {/* ── 사용 흐름 + 기능 ── */}
      <section className="px-6 py-14">
        <div className="max-w-6xl mx-auto">
          <h2 className="text-2xl font-bold text-text-main text-center mb-3">사용 흐름</h2>
          <p className="text-sm text-slate-400 text-center mb-12">도면 업로드부터 GLB 다운로드까지, 4단계로 완성됩니다</p>
          <div className="flex flex-col md:flex-row items-stretch gap-0">
            {[
              { icon: FileUp,     label: '도면 업로드',  desc: 'PDF·DXF·DWG 도면에서 공간 구조와 입구·소방시설 위치를 자동 인식합니다', bg: 'bg-blue-500/10',    border: 'border-blue-500/20',    color: 'text-blue-400' },
              { icon: ScanSearch, label: 'AI 분석',      desc: '브랜드 매뉴얼 기반으로 집기 배치와 동선을 자동 설계합니다',              bg: 'bg-violet-500/10',  border: 'border-violet-500/20',  color: 'text-violet-400' },
              { icon: BoxIcon,    label: '3D 결과 확인', desc: '실시간 3D 뷰어에서 배치 결과를 바로 확인하고 조정할 수 있습니다',         bg: 'bg-emerald-500/10', border: 'border-emerald-500/20', color: 'text-emerald-400' },
              { icon: Download,   label: 'GLB 다운로드', desc: '3D 결과물을 GLB 파일로 다운로드해 SketchUp에 바로 연동할 수 있습니다',    bg: 'bg-orange-500/10',  border: 'border-orange-500/20',  color: 'text-orange-400' },
            ].map(({ icon: Icon, label, desc, bg, border, color }, i, arr) => (
              <Fragment key={label}>
                <BorderFlash delay={i * 600} flashClass="bg-flash-warm" className="flex-1">
                <div className="h-full bg-white/3 border border-white/10 rounded-2xl p-6">
                  <div className={`w-14 h-14 rounded-xl ${bg} border ${border} flex items-center justify-center mb-4`}>
                    <Icon size={28} className={color} />
                  </div>
                  <p className="text-base font-bold text-text-main mb-2">{label}</p>
                  <p className="text-xs text-slate-400 leading-relaxed">{desc}</p>
                </div>
                </BorderFlash>
                {i < arr.length - 1 && (
                  <div className="hidden md:flex items-center justify-center w-10 flex-shrink-0">
                    <ArrowRight
                      size={18}
                      style={{
                        color: '#818cf8',
                        animation: `pulse 1.2s ease-in-out infinite`,
                        animationDelay: `${i * 0.4}s`,
                        filter: 'drop-shadow(0 0 6px #6366f1)',
                      }}
                    />
                  </div>
                )}
              </Fragment>
            ))}
          </div>
        </div>
      </section>

      <div className="h-px bg-gradient-to-r from-transparent via-white/10 to-transparent mx-8" />

      {/* ── 하단 CTA ── */}
      <section className="relative px-6 py-24 text-center overflow-hidden">
        {/* 배경 강화 */}
        <div className="absolute inset-0 bg-gradient-to-br from-primary/20 via-primary/5 to-emerald-500/10 pointer-events-none" />
        <div className="absolute inset-0 bg-gradient-to-t from-[#0d1117] via-transparent to-[#0d1117] pointer-events-none" />
        <div className="absolute inset-0" style={{ backgroundImage: 'radial-gradient(circle at 50% 50%, rgba(99,102,241,0.12) 0%, transparent 65%)' }} />

        <div className="relative z-10 max-w-3xl mx-auto">
          <h2 className="text-2xl md:text-3xl font-bold text-text-main mb-4">지금 바로 사용해 보세요</h2>
          <p className="text-sm text-slate-400 mb-12">도면과 브랜드 파일만 준비하면 됩니다</p>

          <div className="grid grid-cols-3 gap-8 mb-12 max-w-lg mx-auto">
            <FadeIn delay={0} className="text-center">
              <p className="text-3xl font-bold text-white mb-1">90%</p>
              <p className="text-xs text-slate-500">배치 작업 시간 단축</p>
            </FadeIn>
            <FadeIn delay={150} className="text-center">
              <p className="text-3xl font-bold text-white mb-1">3D</p>
              <p className="text-xs text-slate-500">즉시 결과 확인</p>
            </FadeIn>
            <FadeIn delay={300} className="text-center">
              <p className="text-3xl font-bold text-white mb-1">GLB</p>
              <p className="text-xs text-slate-500">SketchUp 바로 연동</p>
            </FadeIn>
          </div>

          <div className="flex items-center justify-center">
            <button
              onClick={handleStart}
              className="flex items-center justify-center gap-2 bg-primary text-white font-bold rounded-xl px-8 py-3.5 text-sm hover:bg-primary/90 transition-colors"
            >
              시작하기 <ArrowRight size={16} />
            </button>
          </div>
        </div>
      </section>

      {/* ── 맨 위로 버튼 ── */}
      <button
        onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
        className="fixed bottom-8 right-8 w-12 h-12 rounded-full bg-primary flex items-center justify-center shadow-lg shadow-primary/30 hover:bg-primary/90 transition-colors z-50"
        aria-label="맨 위로"
      >
        <ArrowRight size={20} className="text-white -rotate-90" />
      </button>

    </main>
  );
}
