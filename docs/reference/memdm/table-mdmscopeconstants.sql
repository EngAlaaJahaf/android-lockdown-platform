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
-- Name: mdmscopeconstants; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.mdmscopeconstants (
    mdm_scope_id integer NOT NULL,
    mdm_scope_name public.citext NOT NULL,
    CONSTRAINT mdmscopeconstants_283764737_c CHECK ((length((mdm_scope_name)::text) <= 250))
);


--
-- Name: mdmscopeconstants mdmscopeconstants_pk; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mdmscopeconstants
    ADD CONSTRAINT mdmscopeconstants_pk PRIMARY KEY (mdm_scope_id);


--
-- Name: mdmscopeconstants mdmscopeconstants_uk1; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mdmscopeconstants
    ADD CONSTRAINT mdmscopeconstants_uk1 UNIQUE (mdm_scope_name);


--
-- PostgreSQL database dump complete
--

