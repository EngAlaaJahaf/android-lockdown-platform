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
-- Name: mdandroiddevicerestriction; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.mdandroiddevicerestriction (
    resource_id bigint NOT NULL,
    allow_camera integer,
    allow_background_data integer,
    activate_data_network integer,
    allow_bluetooth integer,
    allow_nfc integer,
    device_admin_enabled integer,
    allow_disabling_cellular_data integer DEFAULT '-1'::integer NOT NULL,
    allow_disabling_gps integer DEFAULT '-1'::integer NOT NULL
);


--
-- Name: mdandroiddevicerestriction mdandroiddevicerestriction_pk; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mdandroiddevicerestriction
    ADD CONSTRAINT mdandroiddevicerestriction_pk PRIMARY KEY (resource_id);


--
-- Name: mdandroiddevicerestriction mdandroiddevicerestriction_fk; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mdandroiddevicerestriction
    ADD CONSTRAINT mdandroiddevicerestriction_fk FOREIGN KEY (resource_id) REFERENCES public.manageddevice(resource_id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

