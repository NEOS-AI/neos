--
-- PostgreSQL database dump
--

-- Dumped from database version 17.11 (Debian 17.11-1.pgdg13+2)
-- Dumped by pg_dump version 17.5 (Homebrew)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: deep_analysis_blobs; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.deep_analysis_blobs (
    run_id character varying(8) NOT NULL,
    content_hash character varying(16) NOT NULL,
    url text NOT NULL,
    http_status integer NOT NULL,
    fetched_at timestamp with time zone DEFAULT now() NOT NULL,
    raw_text text
);


ALTER TABLE public.deep_analysis_blobs OWNER TO postgres;

--
-- Name: deep_analysis_claims; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.deep_analysis_claims (
    id character varying(8) NOT NULL,
    run_id character varying(8) NOT NULL,
    question_id character varying(8) NOT NULL,
    text text NOT NULL,
    hash character varying(16) NOT NULL,
    status character varying(12) DEFAULT 'pending'::character varying NOT NULL,
    confidence real NOT NULL,
    kind character varying(12) DEFAULT 'quote'::character varying NOT NULL,
    computation text,
    CONSTRAINT ck_deep_analysis_claims_kind CHECK (((kind)::text = ANY ((ARRAY['quote'::character varying, 'computed'::character varying])::text[]))),
    CONSTRAINT deep_analysis_claims_confidence_check CHECK (((confidence >= (0)::double precision) AND (confidence <= (1)::double precision))),
    CONSTRAINT deep_analysis_claims_status_check CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'verified'::character varying, 'rejected'::character varying, 'unverified'::character varying])::text[])))
);


ALTER TABLE public.deep_analysis_claims OWNER TO postgres;

--
-- Name: deep_analysis_events; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.deep_analysis_events (
    seq bigint NOT NULL,
    run_id character varying(8) NOT NULL,
    ts timestamp with time zone DEFAULT now() NOT NULL,
    kind character varying(40) NOT NULL,
    qid character varying(8),
    payload text DEFAULT '{}'::text NOT NULL
);


ALTER TABLE public.deep_analysis_events OWNER TO postgres;

--
-- Name: deep_analysis_events_seq_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.deep_analysis_events_seq_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.deep_analysis_events_seq_seq OWNER TO postgres;

--
-- Name: deep_analysis_events_seq_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.deep_analysis_events_seq_seq OWNED BY public.deep_analysis_events.seq;


--
-- Name: deep_analysis_evidence; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.deep_analysis_evidence (
    id character varying(8) NOT NULL,
    run_id character varying(8) NOT NULL,
    claim_id character varying(8) NOT NULL,
    source_url text NOT NULL,
    excerpt text NOT NULL,
    raw_ref character varying(16) NOT NULL,
    det_grade character varying(40),
    agent_grade character varying(20)
);


ALTER TABLE public.deep_analysis_evidence OWNER TO postgres;

--
-- Name: deep_analysis_feedback; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.deep_analysis_feedback (
    id bigint NOT NULL,
    run_id character varying(8) NOT NULL,
    claim_id character varying(8) NOT NULL,
    code character varying(40) NOT NULL,
    detail text NOT NULL,
    salvage text,
    attempt integer NOT NULL,
    resolved integer DEFAULT 0 NOT NULL,
    CONSTRAINT deep_analysis_feedback_attempt_check CHECK ((attempt > 0)),
    CONSTRAINT deep_analysis_feedback_resolved_check CHECK ((resolved = ANY (ARRAY[0, 1])))
);


ALTER TABLE public.deep_analysis_feedback OWNER TO postgres;

--
-- Name: deep_analysis_feedback_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.deep_analysis_feedback_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.deep_analysis_feedback_id_seq OWNER TO postgres;

--
-- Name: deep_analysis_feedback_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.deep_analysis_feedback_id_seq OWNED BY public.deep_analysis_feedback.id;


--
-- Name: deep_analysis_questions; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.deep_analysis_questions (
    id character varying(8) NOT NULL,
    run_id character varying(8) NOT NULL,
    parent_id character varying(8),
    text text NOT NULL,
    status character varying(20) DEFAULT 'open'::character varying NOT NULL,
    depth integer NOT NULL,
    value_est real NOT NULL,
    confidence real DEFAULT 0 NOT NULL,
    spent_tokens integer DEFAULT 0 NOT NULL,
    cap_tokens integer NOT NULL,
    fail_streak integer DEFAULT 0 NOT NULL,
    evidence_bytes integer DEFAULT 0 NOT NULL,
    CONSTRAINT deep_analysis_questions_cap_tokens_check CHECK ((cap_tokens > 0)),
    CONSTRAINT deep_analysis_questions_confidence_check CHECK (((confidence >= (0)::double precision) AND (confidence <= (1)::double precision))),
    CONSTRAINT deep_analysis_questions_depth_check CHECK ((depth >= 0)),
    CONSTRAINT deep_analysis_questions_fail_streak_check CHECK ((fail_streak >= 0)),
    CONSTRAINT deep_analysis_questions_spent_tokens_check CHECK ((spent_tokens >= 0)),
    CONSTRAINT deep_analysis_questions_status_check CHECK (((status)::text = ANY ((ARRAY['open'::character varying, 'investigating'::character varying, 'resolved'::character varying, 'split'::character varying, 'abandoned'::character varying])::text[]))),
    CONSTRAINT deep_analysis_questions_value_est_check CHECK (((value_est >= (0)::double precision) AND (value_est <= (1)::double precision)))
);


ALTER TABLE public.deep_analysis_questions OWNER TO postgres;

--
-- Name: deep_analysis_reports; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.deep_analysis_reports (
    id bigint NOT NULL,
    period_start timestamp without time zone NOT NULL,
    period_end timestamp without time zone NOT NULL,
    signals jsonb NOT NULL,
    created_at timestamp without time zone DEFAULT (now() AT TIME ZONE 'UTC'::text) NOT NULL
);


ALTER TABLE public.deep_analysis_reports OWNER TO postgres;

--
-- Name: deep_analysis_reports_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.deep_analysis_reports_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.deep_analysis_reports_id_seq OWNER TO postgres;

--
-- Name: deep_analysis_reports_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.deep_analysis_reports_id_seq OWNED BY public.deep_analysis_reports.id;


--
-- Name: deep_analysis_runs; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.deep_analysis_runs (
    id character varying(8) NOT NULL,
    root_question text NOT NULL,
    profile character varying(20) DEFAULT 'default'::character varying NOT NULL,
    status character varying(20) DEFAULT 'running'::character varying NOT NULL,
    user_id character varying(255),
    conversation_id character varying(255),
    assistant_message_id character varying(255),
    report_path text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT deep_analysis_runs_profile_check CHECK (((profile)::text = ANY ((ARRAY['dev'::character varying, 'default'::character varying])::text[]))),
    CONSTRAINT deep_analysis_runs_status_check CHECK (((status)::text = ANY ((ARRAY['running'::character varying, 'completed'::character varying, 'failed'::character varying])::text[])))
);


ALTER TABLE public.deep_analysis_runs OWNER TO postgres;

--
-- Name: deep_analysis_events seq; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.deep_analysis_events ALTER COLUMN seq SET DEFAULT nextval('public.deep_analysis_events_seq_seq'::regclass);


--
-- Name: deep_analysis_feedback id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.deep_analysis_feedback ALTER COLUMN id SET DEFAULT nextval('public.deep_analysis_feedback_id_seq'::regclass);


--
-- Name: deep_analysis_reports id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.deep_analysis_reports ALTER COLUMN id SET DEFAULT nextval('public.deep_analysis_reports_id_seq'::regclass);


--
-- Name: deep_analysis_blobs deep_analysis_blobs_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.deep_analysis_blobs
    ADD CONSTRAINT deep_analysis_blobs_pkey PRIMARY KEY (run_id, content_hash);


--
-- Name: deep_analysis_claims deep_analysis_claims_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.deep_analysis_claims
    ADD CONSTRAINT deep_analysis_claims_pkey PRIMARY KEY (run_id, id);


--
-- Name: deep_analysis_claims deep_analysis_claims_run_id_hash_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.deep_analysis_claims
    ADD CONSTRAINT deep_analysis_claims_run_id_hash_key UNIQUE (run_id, hash);


--
-- Name: deep_analysis_events deep_analysis_events_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.deep_analysis_events
    ADD CONSTRAINT deep_analysis_events_pkey PRIMARY KEY (seq);


--
-- Name: deep_analysis_evidence deep_analysis_evidence_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.deep_analysis_evidence
    ADD CONSTRAINT deep_analysis_evidence_pkey PRIMARY KEY (id);


--
-- Name: deep_analysis_feedback deep_analysis_feedback_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.deep_analysis_feedback
    ADD CONSTRAINT deep_analysis_feedback_pkey PRIMARY KEY (id);


--
-- Name: deep_analysis_questions deep_analysis_questions_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.deep_analysis_questions
    ADD CONSTRAINT deep_analysis_questions_pkey PRIMARY KEY (run_id, id);


--
-- Name: deep_analysis_reports deep_analysis_reports_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.deep_analysis_reports
    ADD CONSTRAINT deep_analysis_reports_pkey PRIMARY KEY (id);


--
-- Name: deep_analysis_runs deep_analysis_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.deep_analysis_runs
    ADD CONSTRAINT deep_analysis_runs_pkey PRIMARY KEY (id);


--
-- Name: idx_da_claims_run_question; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_da_claims_run_question ON public.deep_analysis_claims USING btree (run_id, question_id);


--
-- Name: idx_da_events_run_qid_kind; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_da_events_run_qid_kind ON public.deep_analysis_events USING btree (run_id, qid, kind);


--
-- Name: idx_da_events_ts; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_da_events_ts ON public.deep_analysis_events USING btree (ts);


--
-- Name: idx_da_evidence_run_claim; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_da_evidence_run_claim ON public.deep_analysis_evidence USING btree (run_id, claim_id);


--
-- Name: idx_da_feedback_run_claim; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_da_feedback_run_claim ON public.deep_analysis_feedback USING btree (run_id, claim_id, resolved);


--
-- Name: idx_da_questions_run_status; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_da_questions_run_status ON public.deep_analysis_questions USING btree (run_id, status);


--
-- Name: idx_da_reports_created; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_da_reports_created ON public.deep_analysis_reports USING btree (created_at DESC);


--
-- Name: deep_analysis_events deep_analysis_events_append_only; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER deep_analysis_events_append_only BEFORE DELETE OR UPDATE ON public.deep_analysis_events FOR EACH ROW EXECUTE FUNCTION public.deep_analysis_events_reject_mutation();


--
-- Name: deep_analysis_blobs deep_analysis_blobs_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.deep_analysis_blobs
    ADD CONSTRAINT deep_analysis_blobs_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.deep_analysis_runs(id) ON DELETE CASCADE;


--
-- Name: deep_analysis_claims deep_analysis_claims_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.deep_analysis_claims
    ADD CONSTRAINT deep_analysis_claims_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.deep_analysis_runs(id) ON DELETE CASCADE;


--
-- Name: deep_analysis_claims deep_analysis_claims_run_id_question_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.deep_analysis_claims
    ADD CONSTRAINT deep_analysis_claims_run_id_question_id_fkey FOREIGN KEY (run_id, question_id) REFERENCES public.deep_analysis_questions(run_id, id);


--
-- Name: deep_analysis_events deep_analysis_events_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.deep_analysis_events
    ADD CONSTRAINT deep_analysis_events_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.deep_analysis_runs(id) ON DELETE CASCADE;


--
-- Name: deep_analysis_evidence deep_analysis_evidence_run_id_claim_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.deep_analysis_evidence
    ADD CONSTRAINT deep_analysis_evidence_run_id_claim_id_fkey FOREIGN KEY (run_id, claim_id) REFERENCES public.deep_analysis_claims(run_id, id) ON DELETE CASCADE;


--
-- Name: deep_analysis_evidence deep_analysis_evidence_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.deep_analysis_evidence
    ADD CONSTRAINT deep_analysis_evidence_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.deep_analysis_runs(id) ON DELETE CASCADE;


--
-- Name: deep_analysis_evidence deep_analysis_evidence_run_id_raw_ref_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.deep_analysis_evidence
    ADD CONSTRAINT deep_analysis_evidence_run_id_raw_ref_fkey FOREIGN KEY (run_id, raw_ref) REFERENCES public.deep_analysis_blobs(run_id, content_hash);


--
-- Name: deep_analysis_feedback deep_analysis_feedback_run_id_claim_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.deep_analysis_feedback
    ADD CONSTRAINT deep_analysis_feedback_run_id_claim_id_fkey FOREIGN KEY (run_id, claim_id) REFERENCES public.deep_analysis_claims(run_id, id) ON DELETE CASCADE;


--
-- Name: deep_analysis_feedback deep_analysis_feedback_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.deep_analysis_feedback
    ADD CONSTRAINT deep_analysis_feedback_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.deep_analysis_runs(id) ON DELETE CASCADE;


--
-- Name: deep_analysis_questions deep_analysis_questions_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.deep_analysis_questions
    ADD CONSTRAINT deep_analysis_questions_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.deep_analysis_runs(id) ON DELETE CASCADE;


--
-- Name: deep_analysis_questions deep_analysis_questions_run_id_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.deep_analysis_questions
    ADD CONSTRAINT deep_analysis_questions_run_id_parent_id_fkey FOREIGN KEY (run_id, parent_id) REFERENCES public.deep_analysis_questions(run_id, id);


--
-- Name: deep_analysis_runs deep_analysis_runs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.deep_analysis_runs
    ADD CONSTRAINT deep_analysis_runs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id) ON DELETE SET NULL;


--
-- Name: deep_analysis_runs fk_da_runs_conversation; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.deep_analysis_runs
    ADD CONSTRAINT fk_da_runs_conversation FOREIGN KEY (conversation_id) REFERENCES public.conversations(conversation_id) ON DELETE SET NULL;


--
-- PostgreSQL database dump complete
--

