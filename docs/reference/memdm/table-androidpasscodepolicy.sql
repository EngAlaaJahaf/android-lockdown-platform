--
-- PostgreSQL database dump
--

-- Dumped from database version 14.13
-- Dumped by pg_dump version 14.13

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
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
-- Name: androidpasscodepolicy; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.androidpasscodepolicy (
    config_data_item_id bigint NOT NULL,
    passcode_type integer DEFAULT '-1'::integer NOT NULL,
    min_passcode_length integer DEFAULT '-1'::integer NOT NULL,
    auto_lock_idle_for integer DEFAULT '-1'::integer NOT NULL,
    max_failed_attempts integer DEFAULT '-1'::integer NOT NULL,
    max_passcode_age integer DEFAULT '-1'::integer NOT NULL,
    no_of_passcode_maintained integer DEFAULT '-1'::integer NOT NULL,
    min_lower_case_length integer DEFAULT '-1'::integer NOT NULL,
    min_non_letter_length integer DEFAULT '-1'::integer NOT NULL,
    min_numeric_length integer DEFAULT '-1'::integer NOT NULL,
    min_symbol_length integer DEFAULT '-1'::integer NOT NULL,
    min_upper_case_length integer DEFAULT '-1'::integer NOT NULL,
    min_letter_length integer DEFAULT '-1'::integer NOT NULL,
    max_chars integer DEFAULT '-1'::integer NOT NULL,
    max_numeric_sequence integer DEFAULT '-1'::integer NOT NULL,
    grace_period integer DEFAULT '-1'::integer NOT NULL,
    allow_fingerprint integer DEFAULT '-1'::integer NOT NULL,
    allow_iris_scan boolean DEFAULT true,
    allow_face_unlock boolean DEFAULT true,
    allow_one_lock boolean DEFAULT true,
    scope_for_passcode integer DEFAULT 0 NOT NULL,
    set_default_passcode boolean DEFAULT false NOT NULL,
    allow_change_default_passcode boolean DEFAULT true NOT NULL,
    allow_trust_agents integer DEFAULT 1 NOT NULL,
    new_default_passcode_id bigint,
    passcode_complexity integer,
    strong_auth_timeout integer DEFAULT 0
);


--
-- Name: androidpasscodepolicy androidpasscodepolicy_pk; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.androidpasscodepolicy
    ADD CONSTRAINT androidpasscodepolicy_pk PRIMARY KEY (config_data_item_id);


--
-- Name: androidpasscodepolicy_fk2_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX androidpasscodepolicy_fk2_idx ON public.androidpasscodepolicy USING btree (new_default_passcode_id);


--
-- Name: androidpasscodepolicy androidpasscodepolicy_fk; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.androidpasscodepolicy
    ADD CONSTRAINT androidpasscodepolicy_fk FOREIGN KEY (config_data_item_id) REFERENCES public.configdataitem(config_data_item_id) ON DELETE CASCADE;


--
-- Name: androidpasscodepolicy androidpasscodepolicy_fk2; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.androidpasscodepolicy
    ADD CONSTRAINT androidpasscodepolicy_fk2 FOREIGN KEY (new_default_passcode_id) REFERENCES public.mdmmanagedpassword(managed_password_id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

