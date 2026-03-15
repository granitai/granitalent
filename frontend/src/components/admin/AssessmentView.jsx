import React, { useState } from 'react'
import { cn } from '../../lib/utils'
import {
  TrendingUp, TrendingDown, Award, AlertTriangle, CheckCircle2, XCircle,
  Languages, Target, MessageSquare, Lightbulb, FileCheck, BookOpen,
  Brain, ChevronDown, ChevronUp, Quote, Sparkles, ShieldCheck, ShieldX, ShieldQuestion
} from 'lucide-react'

// ── Score category definitions ──────────────────────────────────────────────
const SCORE_CATEGORIES = [
  { key: 'technical_skills', label: 'Technical Skills', icon: Target, color: 'blue' },
  { key: 'job_fit', label: 'Job Fit', icon: Lightbulb, color: 'violet' },
  { key: 'communication', label: 'Communication', icon: MessageSquare, color: 'cyan' },
  { key: 'problem_solving', label: 'Problem Solving', icon: Brain, color: 'amber' },
  { key: 'cv_consistency', label: 'CV Consistency', icon: FileCheck, color: 'emerald' },
]

const CEFR_INFO = {
  A1: { label: 'Beginner', bg: 'bg-red-500', ring: 'ring-red-200', text: 'text-white' },
  A2: { label: 'Elementary', bg: 'bg-orange-500', ring: 'ring-orange-200', text: 'text-white' },
  B1: { label: 'Intermediate', bg: 'bg-amber-500', ring: 'ring-amber-200', text: 'text-white' },
  B2: { label: 'Upper Int.', bg: 'bg-blue-500', ring: 'ring-blue-200', text: 'text-white' },
  C1: { label: 'Advanced', bg: 'bg-emerald-500', ring: 'ring-emerald-200', text: 'text-white' },
  C2: { label: 'Mastery', bg: 'bg-green-600', ring: 'ring-green-200', text: 'text-white' },
}

// ── Utility functions ───────────────────────────────────────────────────────
function scoreColor(score) {
  if (score >= 7) return 'text-emerald-600'
  if (score >= 5) return 'text-amber-600'
  if (score >= 3) return 'text-orange-600'
  return 'text-red-600'
}

function scoreBg(score) {
  if (score >= 7) return 'bg-emerald-500'
  if (score >= 5) return 'bg-amber-500'
  if (score >= 3) return 'bg-orange-500'
  return 'bg-red-500'
}

function scoreTrack(score) {
  if (score >= 7) return 'bg-emerald-100'
  if (score >= 5) return 'bg-amber-100'
  if (score >= 3) return 'bg-orange-100'
  return 'bg-red-100'
}

function scoreLabel(score) {
  if (score >= 8) return 'Excellent'
  if (score >= 7) return 'Good'
  if (score >= 5) return 'Average'
  if (score >= 3) return 'Below Average'
  return 'Poor'
}

// ── Score Ring (circular progress) ──────────────────────────────────────────
function ScoreRing({ score, size = 'lg' }) {
  const config = {
    lg: { radius: 48, stroke: 7, textSize: 'text-3xl', subSize: 'text-xs' },
    md: { radius: 32, stroke: 5, textSize: 'text-xl', subSize: 'text-[10px]' },
    sm: { radius: 22, stroke: 4, textSize: 'text-sm', subSize: 'text-[8px]' },
  }
  const { radius, stroke, textSize, subSize } = config[size]
  const circumference = 2 * Math.PI * radius
  const progress = Math.min((score / 10), 1) * circumference
  const svgSize = (radius + stroke) * 2

  return (
    <div className="relative inline-flex items-center justify-center">
      <svg width={svgSize} height={svgSize} className="-rotate-90">
        <circle
          cx={radius + stroke} cy={radius + stroke} r={radius}
          fill="none" strokeWidth={stroke}
          className="text-slate-100" stroke="currentColor"
        />
        <circle
          cx={radius + stroke} cy={radius + stroke} r={radius}
          fill="none" strokeWidth={stroke} strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference - progress}
          className={cn(scoreBg(score).replace('bg-', 'text-'))}
          stroke="currentColor"
          style={{ transition: 'stroke-dashoffset 1s ease-out' }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className={cn('font-bold tracking-tight', textSize, scoreColor(score))}>
          {typeof score === 'number' ? score.toFixed(1) : '--'}
        </span>
        <span className={cn('font-medium text-slate-400', subSize)}>/10</span>
      </div>
    </div>
  )
}

// ── Recommendation Hero ─────────────────────────────────────────────────────
function RecommendationHero({ recommendation, overallScore, summary }) {
  const recConfig = {
    recommended: {
      icon: ShieldCheck,
      label: 'Recommended',
      gradient: 'from-emerald-500 to-teal-600',
      bgLight: 'bg-emerald-50',
      border: 'border-emerald-200',
      iconColor: 'text-emerald-600',
      labelColor: 'text-emerald-700',
      ringColor: 'ring-emerald-500/20',
    },
    not_recommended: {
      icon: ShieldX,
      label: 'Not Recommended',
      gradient: 'from-red-500 to-rose-600',
      bgLight: 'bg-red-50',
      border: 'border-red-200',
      iconColor: 'text-red-600',
      labelColor: 'text-red-700',
      ringColor: 'ring-red-500/20',
    },
    maybe: {
      icon: ShieldQuestion,
      label: 'Under Consideration',
      gradient: 'from-amber-500 to-orange-500',
      bgLight: 'bg-amber-50',
      border: 'border-amber-200',
      iconColor: 'text-amber-600',
      labelColor: 'text-amber-700',
      ringColor: 'ring-amber-500/20',
    },
  }
  const cfg = recConfig[recommendation] || recConfig.maybe

  return (
    <div className={cn('relative overflow-hidden rounded-2xl border p-6', cfg.border, cfg.bgLight)}>
      {/* Subtle gradient accent bar at top */}
      <div className={cn('absolute inset-x-0 top-0 h-1 bg-gradient-to-r', cfg.gradient)} />

      <div className="flex flex-col sm:flex-row items-center gap-6 pt-1">
        {/* Score ring */}
        <div className={cn('rounded-full p-3 ring-4', cfg.ringColor, 'bg-white shadow-sm')}>
          <ScoreRing score={overallScore ?? 0} size="lg" />
        </div>

        {/* Content */}
        <div className="flex-1 text-center sm:text-left">
          <div className="flex items-center justify-center sm:justify-start gap-2 mb-2">
            <cfg.icon className={cn('h-5 w-5', cfg.iconColor)} />
            <span className={cn('text-base font-bold', cfg.labelColor)}>{cfg.label}</span>
          </div>
          {summary && (
            <p className="text-sm text-slate-600 leading-relaxed max-w-xl">{summary}</p>
          )}
          <div className="mt-3 flex items-center justify-center sm:justify-start gap-3">
            <span className={cn('inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold', scoreBg(overallScore ?? 0), 'text-white')}>
              <Sparkles className="h-3 w-3" />
              {scoreLabel(overallScore ?? 0)}
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Score Card (individual category) ────────────────────────────────────────
function ScoreCard({ label, score, justification, icon: Icon, color }) {
  const [expanded, setExpanded] = useState(false)

  const colorMap = {
    blue: { iconBg: 'bg-blue-100', iconText: 'text-blue-600' },
    violet: { iconBg: 'bg-violet-100', iconText: 'text-violet-600' },
    cyan: { iconBg: 'bg-cyan-100', iconText: 'text-cyan-600' },
    amber: { iconBg: 'bg-amber-100', iconText: 'text-amber-600' },
    emerald: { iconBg: 'bg-emerald-100', iconText: 'text-emerald-600' },
  }
  const c = colorMap[color] || colorMap.blue

  return (
    <div className="group rounded-xl border border-slate-200 bg-white p-4 transition-shadow hover:shadow-md">
      <div className="flex items-start gap-3">
        {/* Icon */}
        <div className={cn('flex h-9 w-9 shrink-0 items-center justify-center rounded-lg', c.iconBg)}>
          <Icon className={cn('h-4.5 w-4.5', c.iconText)} />
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-semibold text-slate-800">{label}</span>
            <div className="flex items-center gap-2">
              <span className={cn('text-lg font-bold tabular-nums leading-none', scoreColor(score))}>
                {score}
              </span>
              <span className="text-xs text-slate-400 font-medium">/10</span>
            </div>
          </div>

          {/* Progress bar */}
          <div className={cn('h-2 w-full rounded-full', scoreTrack(score))}>
            <div
              className={cn('h-2 rounded-full transition-all duration-700 ease-out', scoreBg(score))}
              style={{ width: `${(score / 10) * 100}%` }}
            />
          </div>

          {/* Justification (collapsible) */}
          {justification && (
            <div className="mt-2">
              <button
                onClick={() => setExpanded(!expanded)}
                className="flex items-center gap-1 text-xs font-medium text-slate-500 hover:text-slate-700 transition-colors"
              >
                <Quote className="h-3 w-3" />
                {expanded ? 'Hide details' : 'View details'}
                {expanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
              </button>
              {expanded && (
                <p className="mt-2 text-xs text-slate-600 leading-relaxed bg-slate-50 rounded-lg p-3 border border-slate-100">
                  {justification}
                </p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Language Proficiency Card ───────────────────────────────────────────────
function LanguageCard({ language, cefr_level, score, details }) {
  const [expanded, setExpanded] = useState(false)
  const cefr = CEFR_INFO[cefr_level]

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 transition-shadow hover:shadow-md">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-violet-100">
            <Languages className="h-4 w-4 text-violet-600" />
          </div>
          <span className="text-sm font-semibold text-slate-800">{language}</span>
        </div>
        <div className="flex items-center gap-2">
          {cefr_level && cefr && (
            <span className={cn(
              'inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-bold ring-1',
              cefr.bg, cefr.text, cefr.ring
            )}>
              {cefr_level}
              <span className="text-[10px] font-medium opacity-80">{cefr.label}</span>
            </span>
          )}
        </div>
      </div>

      {/* Score + bar */}
      <div className="flex items-center gap-3 mb-1">
        <div className={cn('h-2 flex-1 rounded-full', scoreTrack(score))}>
          <div
            className={cn('h-2 rounded-full transition-all duration-700', scoreBg(score))}
            style={{ width: `${(score / 10) * 100}%` }}
          />
        </div>
        <span className={cn('text-sm font-bold tabular-nums', scoreColor(score))}>
          {score}/10
        </span>
      </div>

      {/* Details */}
      {details && (
        <div className="mt-2">
          <button
            onClick={() => setExpanded(!expanded)}
            className="flex items-center gap-1 text-xs font-medium text-slate-500 hover:text-slate-700 transition-colors"
          >
            <Quote className="h-3 w-3" />
            {expanded ? 'Hide analysis' : 'View analysis'}
            {expanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
          </button>
          {expanded && (
            <p className="mt-2 text-xs text-slate-600 leading-relaxed bg-slate-50 rounded-lg p-3 border border-slate-100">
              {details}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

// ── Main Component ──────────────────────────────────────────────────────────
export default function AssessmentView({ assessment, evaluationScores }) {
  // Try to parse structured assessment from the assessment text itself
  let structured = null
  try {
    const parsed = JSON.parse(assessment)
    if (parsed && typeof parsed === 'object' && parsed.scores) {
      structured = parsed
    }
  } catch {
    // Not JSON — check evaluationScores prop
  }

  // If we have evaluationScores but no structured assessment, build a partial one
  if (!structured && evaluationScores && typeof evaluationScores === 'object') {
    if (evaluationScores.technical_skills !== undefined || evaluationScores.overall_score !== undefined) {
      structured = {
        overall_score: evaluationScores.overall_score,
        scores: {
          technical_skills: { score: evaluationScores.technical_skills, justification: '' },
          job_fit: { score: evaluationScores.job_fit, justification: '' },
          communication: { score: evaluationScores.communication, justification: '' },
          problem_solving: { score: evaluationScores.problem_solving, justification: '' },
          cv_consistency: { score: evaluationScores.cv_consistency, justification: '' },
        },
        language_proficiency: evaluationScores.linguistic_capacity
          ? Object.entries(evaluationScores.linguistic_capacity).map(([lang, score]) => ({
              language: lang, score, cefr_level: null, details: ''
            }))
          : [],
        recommendation: null,
        summary: null,
        strengths: [],
        improvements: [],
        custom_questions_coverage: [],
      }
    }
  }

  // Fallback: plain text rendering (legacy assessments)
  if (!structured) {
    return (
      <div className="prose prose-sm max-w-none">
        <pre className="whitespace-pre-wrap font-sans text-sm text-slate-700">{assessment}</pre>
      </div>
    )
  }

  const { overall_score, recommendation, summary, scores, language_proficiency, strengths, improvements, custom_questions_coverage } = structured

  return (
    <div className="space-y-8">
      {/* ── Hero: Overall Score + Recommendation ── */}
      <RecommendationHero
        recommendation={recommendation}
        overallScore={overall_score}
        summary={summary}
      />

      {/* ── Score Breakdown Grid ── */}
      {scores && (
        <div>
          <div className="flex items-center gap-2 mb-4">
            <Award className="h-5 w-5 text-brand-500" />
            <h3 className="text-base font-semibold text-slate-900">Score Breakdown</h3>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {SCORE_CATEGORIES.map(({ key, label, icon, color }) => {
              const data = scores[key]
              if (!data) return null
              const s = typeof data === 'object' ? data.score : data
              const j = typeof data === 'object' ? data.justification : ''
              if (s == null) return null
              return (
                <ScoreCard
                  key={key}
                  label={label}
                  score={s}
                  justification={j}
                  icon={icon}
                  color={color}
                />
              )
            })}
          </div>
        </div>
      )}

      {/* ── Language Proficiency ── */}
      {language_proficiency && language_proficiency.length > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-4">
            <BookOpen className="h-5 w-5 text-violet-500" />
            <h3 className="text-base font-semibold text-slate-900">Language Proficiency</h3>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {language_proficiency.map((lp, i) => (
              <LanguageCard key={i} {...lp} />
            ))}
          </div>
        </div>
      )}

      {/* ── Strengths & Improvements ── */}
      {((strengths && strengths.length > 0) || (improvements && improvements.length > 0)) && (
        <div className="grid gap-4 sm:grid-cols-2">
          {strengths && strengths.length > 0 && (
            <div className="rounded-xl border border-emerald-200 bg-gradient-to-br from-emerald-50 to-green-50/50 p-5">
              <div className="flex items-center gap-2 mb-4">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-100">
                  <TrendingUp className="h-4 w-4 text-emerald-600" />
                </div>
                <h4 className="text-sm font-semibold text-emerald-900">Strengths</h4>
              </div>
              <ul className="space-y-2.5">
                {strengths.map((s, i) => (
                  <li key={i} className="flex gap-2.5">
                    <CheckCircle2 className="h-4 w-4 mt-0.5 shrink-0 text-emerald-500" />
                    <span className="text-sm text-emerald-800 leading-relaxed">{s}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {improvements && improvements.length > 0 && (
            <div className="rounded-xl border border-amber-200 bg-gradient-to-br from-amber-50 to-orange-50/50 p-5">
              <div className="flex items-center gap-2 mb-4">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-amber-100">
                  <TrendingDown className="h-4 w-4 text-amber-600" />
                </div>
                <h4 className="text-sm font-semibold text-amber-900">Areas for Improvement</h4>
              </div>
              <ul className="space-y-2.5">
                {improvements.map((s, i) => (
                  <li key={i} className="flex gap-2.5">
                    <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0 text-amber-500" />
                    <span className="text-sm text-amber-800 leading-relaxed">{s}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* ── Custom Questions Coverage ── */}
      {custom_questions_coverage && custom_questions_coverage.length > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-4">
            <FileCheck className="h-5 w-5 text-brand-500" />
            <h3 className="text-base font-semibold text-slate-900">Custom Questions</h3>
            <span className="ml-auto inline-flex items-center rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-600">
              {custom_questions_coverage.filter(cq => cq.answered).length}/{custom_questions_coverage.length} answered
            </span>
          </div>
          <div className="space-y-2">
            {custom_questions_coverage.map((cq, i) => (
              <div
                key={i}
                className={cn(
                  'flex items-start gap-3 rounded-xl border p-4 transition-colors',
                  cq.answered
                    ? 'border-emerald-200 bg-emerald-50/50'
                    : 'border-red-200 bg-red-50/50'
                )}
              >
                <div className={cn(
                  'flex h-6 w-6 shrink-0 items-center justify-center rounded-full mt-0.5',
                  cq.answered ? 'bg-emerald-100' : 'bg-red-100'
                )}>
                  {cq.answered
                    ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" />
                    : <XCircle className="h-3.5 w-3.5 text-red-500" />
                  }
                </div>
                <div className="flex-1 min-w-0">
                  <p className={cn(
                    'text-sm font-medium',
                    cq.answered ? 'text-slate-800' : 'text-slate-600'
                  )}>
                    {cq.question}
                  </p>
                  {cq.answered && cq.summary && cq.summary !== 'Not addressed' ? (
                    <p className="mt-1 text-xs text-slate-500 leading-relaxed">{cq.summary}</p>
                  ) : !cq.answered && (
                    <p className="mt-1 text-xs text-red-500 font-medium">Not addressed during the interview</p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
