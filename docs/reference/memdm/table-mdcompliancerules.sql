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
-- Name: mdcompliancerules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.mdcompliancerules (
    compliance_rule_id bigint NOT NULL,
    customer_id bigint NOT NULL,
    corporate_wipe_rooted_devices boolean DEFAULT false NOT NULL,
    wipe_integrity_failed_devices boolean DEFAULT false NOT NULL,
    wipe_cts_failed_devices boolean DEFAULT false NOT NULL,
    updated_by bigint,
    updated_time bigint DEFAULT '-1'::bigint
);


--
-- Name: mdcompliancerules mdcompliancerules_pk; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mdcompliancerules
    ADD CONSTRAINT mdcompliancerules_pk PRIMARY KEY (compliance_rule_id);


--
-- Name: mdcompliancerules_fk1_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX mdcompliancerules_fk1_idx ON public.mdcompliancerules USING btree (updated_by);


--
-- Name: mdcompliancerules_fk_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX mdcompliancerules_fk_idx ON public.mdcompliancerules USING btree (customer_id);


--
-- Name: mdcompliancerules mdcompliancerules_fk; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mdcompliancerules
    ADD CONSTRAINT mdcompliancerules_fk FOREIGN KEY (customer_id) REFERENCES public.customerinfo(customer_id) ON DELETE CASCADE;


--
-- Name: mdcompliancerules mdcompliancerules_fk1; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mdcompliancerules
    ADD CONSTRAINT mdcompliancerules_fk1 FOREIGN KEY (updated_by) REFERENCES public.aaauser(user_id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

