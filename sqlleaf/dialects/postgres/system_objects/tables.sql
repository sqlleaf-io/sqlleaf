CREATE TABLE pg_catalog.pg_aggregate (
    aggfnoid regproc NOT NULL,
    aggkind "char",
    aggnumdirectargs smallint,
    aggtransfn regproc,
    aggfinalfn regproc,
    aggcombinefn regproc,
    aggserialfn regproc,
    aggdeserialfn regproc,
    aggmtransfn regproc,
    aggminvtransfn regproc,
    aggmfinalfn regproc,
    aggfinalextra boolean,
    aggmfinalextra boolean,
    aggfinalmodify "char",
    aggmfinalmodify "char",
    aggsortop oid,
    aggtranstype oid,
    aggtransspace integer,
    aggmtranstype oid,
    aggmtransspace integer,
    agginitval text COLLATE pg_catalog."C",
    aggminitval text COLLATE pg_catalog."C"
);

CREATE TABLE pg_catalog.pg_am (
    oid oid NOT NULL,
    amname name,
    amhandler regproc,
    amtype "char"
);

CREATE TABLE pg_catalog.pg_amop (
    oid oid NOT NULL,
    amopfamily oid,
    amoplefttype oid,
    amoprighttype oid,
    amopstrategy smallint,
    amoppurpose "char",
    amopopr oid,
    amopmethod oid,
    amopsortfamily oid
);

CREATE TABLE pg_catalog.pg_amproc (
    oid oid NOT NULL,
    amprocfamily oid,
    amproclefttype oid,
    amprocrighttype oid,
    amprocnum smallint,
    amproc regproc
);

CREATE TABLE pg_catalog.pg_attrdef (
    oid oid NOT NULL,
    adrelid oid,
    adnum smallint,
    adbin pg_node_tree COLLATE pg_catalog."C"
);

CREATE TABLE pg_catalog.pg_attribute (
    attrelid oid NOT NULL,
    attname name,
    atttypid oid,
    attlen smallint,
    attnum smallint NOT NULL,
    atttypmod integer,
    attndims smallint,
    attbyval boolean,
    attalign "char",
    attstorage "char",
    attcompression "char",
    attnotnull boolean,
    atthasdef boolean,
    atthasmissing boolean,
    attidentity "char",
    attgenerated "char",
    attisdropped boolean,
    attislocal boolean,
    attinhcount smallint,
    attcollation oid,
    attstattarget smallint,
    attacl aclitem[],
    attoptions text[] COLLATE pg_catalog."C",
    attfdwoptions text[] COLLATE pg_catalog."C",
    attmissingval anyarray
);

CREATE TABLE pg_catalog.pg_auth_members (
    oid oid NOT NULL,
    roleid oid,
    member oid,
    grantor oid,
    admin_option boolean,
    inherit_option boolean,
    set_option boolean
);

CREATE TABLE pg_catalog.pg_authid (
    oid oid NOT NULL,
    rolname name,
    rolsuper boolean,
    rolinherit boolean,
    rolcreaterole boolean,
    rolcreatedb boolean,
    rolcanlogin boolean,
    rolreplication boolean,
    rolbypassrls boolean,
    rolconnlimit integer,
    rolpassword text COLLATE pg_catalog."C",
    rolvaliduntil timestamp with time zone
);

CREATE TABLE pg_catalog.pg_cast (
    oid oid NOT NULL,
    castsource oid,
    casttarget oid,
    castfunc oid,
    castcontext "char",
    castmethod "char"
);

CREATE TABLE pg_catalog.pg_class (
    oid oid NOT NULL,
    relname name,
    relnamespace oid,
    reltype oid,
    reloftype oid,
    relowner oid,
    relam oid,
    relfilenode oid,
    reltablespace oid,
    relpages integer,
    reltuples real,
    relallvisible integer,
    relallfrozen integer,
    reltoastrelid oid,
    relhasindex boolean,
    relisshared boolean,
    relpersistence "char",
    relkind "char",
    relnatts smallint,
    relchecks smallint,
    relhasrules boolean,
    relhastriggers boolean,
    relhassubclass boolean,
    relrowsecurity boolean,
    relforcerowsecurity boolean,
    relispopulated boolean,
    relreplident "char",
    relispartition boolean,
    relrewrite oid,
    relfrozenxid xid,
    relminmxid xid,
    relacl aclitem[],
    reloptions text[] COLLATE pg_catalog."C",
    relpartbound pg_node_tree COLLATE pg_catalog."C"
);

CREATE TABLE pg_catalog.pg_collation (
    oid oid NOT NULL,
    collname name,
    collnamespace oid,
    collowner oid,
    collprovider "char",
    collisdeterministic boolean,
    collencoding integer,
    collcollate text COLLATE pg_catalog."C",
    collctype text COLLATE pg_catalog."C",
    colllocale text COLLATE pg_catalog."C",
    collicurules text COLLATE pg_catalog."C",
    collversion text COLLATE pg_catalog."C"
);

CREATE TABLE pg_catalog.pg_constraint (
    oid oid NOT NULL,
    conname name,
    connamespace oid,
    contype "char",
    condeferrable boolean,
    condeferred boolean,
    conenforced boolean,
    convalidated boolean,
    conrelid oid,
    contypid oid,
    conindid oid,
    conparentid oid,
    confrelid oid,
    confupdtype "char",
    confdeltype "char",
    confmatchtype "char",
    conislocal boolean,
    coninhcount smallint,
    connoinherit boolean,
    conperiod boolean,
    conkey smallint[],
    confkey smallint[],
    conpfeqop oid[],
    conppeqop oid[],
    conffeqop oid[],
    confdelsetcols smallint[],
    conexclop oid[],
    conbin pg_node_tree COLLATE pg_catalog."C"
);

CREATE TABLE pg_catalog.pg_conversion (
    oid oid NOT NULL,
    conname name,
    connamespace oid,
    conowner oid,
    conforencoding integer,
    contoencoding integer,
    conproc regproc,
    condefault boolean
);

CREATE TABLE pg_catalog.pg_database (
    oid oid NOT NULL,
    datname name,
    datdba oid,
    encoding integer,
    datlocprovider "char",
    datistemplate boolean,
    datallowconn boolean,
    dathasloginevt boolean,
    datconnlimit integer,
    datfrozenxid xid,
    datminmxid xid,
    dattablespace oid,
    datcollate text COLLATE pg_catalog."C",
    datctype text COLLATE pg_catalog."C",
    datlocale text COLLATE pg_catalog."C",
    daticurules text COLLATE pg_catalog."C",
    datcollversion text COLLATE pg_catalog."C",
    datacl aclitem[]
);

CREATE TABLE pg_catalog.pg_db_role_setting (
    setdatabase oid NOT NULL,
    setrole oid NOT NULL,
    setconfig text[] COLLATE pg_catalog."C"
);

CREATE TABLE pg_catalog.pg_default_acl (
    oid oid NOT NULL,
    defaclrole oid,
    defaclnamespace oid,
    defaclobjtype "char",
    defaclacl aclitem[]
);

CREATE TABLE pg_catalog.pg_depend (
    classid oid,
    objid oid,
    objsubid integer,
    refclassid oid,
    refobjid oid,
    refobjsubid integer,
    deptype "char"
);

CREATE TABLE pg_catalog.pg_description (
    objoid oid NOT NULL,
    classoid oid NOT NULL,
    objsubid integer NOT NULL,
    description text COLLATE pg_catalog."C"
);

CREATE TABLE pg_catalog.pg_enum (
    oid oid NOT NULL,
    enumtypid oid,
    enumsortorder real,
    enumlabel name
);

CREATE TABLE pg_catalog.pg_event_trigger (
    oid oid NOT NULL,
    evtname name,
    evtevent name,
    evtowner oid,
    evtfoid oid,
    evtenabled "char",
    evttags text[] COLLATE pg_catalog."C"
);

CREATE TABLE pg_catalog.pg_extension (
    oid oid NOT NULL,
    extname name,
    extowner oid,
    extnamespace oid,
    extrelocatable boolean,
    extversion text COLLATE pg_catalog."C",
    extconfig oid[],
    extcondition text[] COLLATE pg_catalog."C"
);

CREATE TABLE pg_catalog.pg_foreign_data_wrapper (
    oid oid NOT NULL,
    fdwname name,
    fdwowner oid,
    fdwhandler oid,
    fdwvalidator oid,
    fdwacl aclitem[],
    fdwoptions text[] COLLATE pg_catalog."C"
);

CREATE TABLE pg_catalog.pg_foreign_server (
    oid oid NOT NULL,
    srvname name,
    srvowner oid,
    srvfdw oid,
    srvtype text COLLATE pg_catalog."C",
    srvversion text COLLATE pg_catalog."C",
    srvacl aclitem[],
    srvoptions text[] COLLATE pg_catalog."C"
);

CREATE TABLE pg_catalog.pg_foreign_table (
    ftrelid oid NOT NULL,
    ftserver oid,
    ftoptions text[] COLLATE pg_catalog."C"
);

CREATE TABLE pg_catalog.pg_index (
    indexrelid oid NOT NULL,
    indrelid oid,
    indnatts smallint,
    indnkeyatts smallint,
    indisunique boolean,
    indnullsnotdistinct boolean,
    indisprimary boolean,
    indisexclusion boolean,
    indimmediate boolean,
    indisclustered boolean,
    indisvalid boolean,
    indcheckxmin boolean,
    indisready boolean,
    indislive boolean,
    indisreplident boolean,
    indkey int2vector,
    indcollation oidvector,
    indclass oidvector,
    indoption int2vector,
    indexprs pg_node_tree COLLATE pg_catalog."C",
    indpred pg_node_tree COLLATE pg_catalog."C"
);

CREATE TABLE pg_catalog.pg_inherits (
    inhrelid oid NOT NULL,
    inhparent oid,
    inhseqno integer NOT NULL,
    inhdetachpending boolean
);

CREATE TABLE pg_catalog.pg_init_privs (
    objoid oid NOT NULL,
    classoid oid NOT NULL,
    objsubid integer NOT NULL,
    privtype "char",
    initprivs aclitem[]
);

CREATE TABLE pg_catalog.pg_language (
    oid oid NOT NULL,
    lanname name,
    lanowner oid,
    lanispl boolean,
    lanpltrusted boolean,
    lanplcallfoid oid,
    laninline oid,
    lanvalidator oid,
    lanacl aclitem[]
);

CREATE TABLE pg_catalog.pg_largeobject (
    loid oid NOT NULL,
    pageno integer NOT NULL,
    data bytea
);

CREATE TABLE pg_catalog.pg_largeobject_metadata (
    oid oid NOT NULL,
    lomowner oid,
    lomacl aclitem[]
);

CREATE TABLE pg_catalog.pg_namespace (
    oid oid NOT NULL,
    nspname name,
    nspowner oid,
    nspacl aclitem[]
);

CREATE TABLE pg_catalog.pg_opclass (
    oid oid NOT NULL,
    opcmethod oid,
    opcname name,
    opcnamespace oid,
    opcowner oid,
    opcfamily oid,
    opcintype oid,
    opcdefault boolean,
    opckeytype oid
);

CREATE TABLE pg_catalog.pg_operator (
    oid oid NOT NULL,
    oprname name,
    oprnamespace oid,
    oprowner oid,
    oprkind "char",
    oprcanmerge boolean,
    oprcanhash boolean,
    oprleft oid,
    oprright oid,
    oprresult oid,
    oprcom oid,
    oprnegate oid,
    oprcode regproc,
    oprrest regproc,
    oprjoin regproc
);

CREATE TABLE pg_catalog.pg_opfamily (
    oid oid NOT NULL,
    opfmethod oid,
    opfname name,
    opfnamespace oid,
    opfowner oid
);

CREATE TABLE pg_catalog.pg_parameter_acl (
    oid oid NOT NULL,
    parname text COLLATE pg_catalog."C",
    paracl aclitem[]
);

CREATE TABLE pg_catalog.pg_partitioned_table (
    partrelid oid NOT NULL,
    partstrat "char",
    partnatts smallint,
    partdefid oid,
    partattrs int2vector,
    partclass oidvector,
    partcollation oidvector,
    partexprs pg_node_tree COLLATE pg_catalog."C"
);

CREATE TABLE pg_catalog.pg_policy (
    oid oid NOT NULL,
    polname name,
    polrelid oid,
    polcmd "char",
    polpermissive boolean,
    polroles oid[],
    polqual pg_node_tree COLLATE pg_catalog."C",
    polwithcheck pg_node_tree COLLATE pg_catalog."C"
);

CREATE TABLE pg_catalog.pg_proc (
    oid oid NOT NULL,
    proname name,
    pronamespace oid,
    proowner oid,
    prolang oid,
    procost real,
    prorows real,
    provariadic oid,
    prosupport regproc,
    prokind "char",
    prosecdef boolean,
    proleakproof boolean,
    proisstrict boolean,
    proretset boolean,
    provolatile "char",
    proparallel "char",
    pronargs smallint,
    pronargdefaults smallint,
    prorettype oid,
    proargtypes oidvector,
    proallargtypes oid[],
    proargmodes "char"[],
    proargnames text[] COLLATE pg_catalog."C",
    proargdefaults pg_node_tree COLLATE pg_catalog."C",
    protrftypes oid[],
    prosrc text COLLATE pg_catalog."C",
    probin text COLLATE pg_catalog."C",
    prosqlbody pg_node_tree COLLATE pg_catalog."C",
    proconfig text[] COLLATE pg_catalog."C",
    proacl aclitem[]
);

CREATE TABLE pg_catalog.pg_publication (
    oid oid NOT NULL,
    pubname name,
    pubowner oid,
    puballtables boolean,
    pubinsert boolean,
    pubupdate boolean,
    pubdelete boolean,
    pubtruncate boolean,
    pubviaroot boolean,
    pubgencols "char"
);

CREATE TABLE pg_catalog.pg_publication_namespace (
    oid oid NOT NULL,
    pnpubid oid,
    pnnspid oid
);

CREATE TABLE pg_catalog.pg_publication_rel (
    oid oid NOT NULL,
    prpubid oid,
    prrelid oid,
    prqual pg_node_tree COLLATE pg_catalog."C",
    prattrs int2vector
);

CREATE TABLE pg_catalog.pg_range (
    rngtypid oid NOT NULL,
    rngsubtype oid,
    rngmultitypid oid,
    rngcollation oid,
    rngsubopc oid,
    rngcanonical regproc,
    rngsubdiff regproc
);

CREATE TABLE pg_catalog.pg_replication_origin (
    roident oid NOT NULL,
    roname text COLLATE pg_catalog."C"
);

CREATE TABLE pg_catalog.pg_rewrite (
    oid oid NOT NULL,
    rulename name,
    ev_class oid,
    ev_type "char",
    ev_enabled "char",
    is_instead boolean,
    ev_qual pg_node_tree COLLATE pg_catalog."C",
    ev_action pg_node_tree COLLATE pg_catalog."C"
);

CREATE TABLE pg_catalog.pg_seclabel (
    objoid oid NOT NULL,
    classoid oid NOT NULL,
    objsubid integer NOT NULL,
    provider text NOT NULL COLLATE pg_catalog."C",
    label text COLLATE pg_catalog."C"
);

CREATE TABLE pg_catalog.pg_sequence (
    seqrelid oid NOT NULL,
    seqtypid oid,
    seqstart bigint,
    seqincrement bigint,
    seqmax bigint,
    seqmin bigint,
    seqcache bigint,
    seqcycle boolean
);

CREATE TABLE pg_catalog.pg_shdepend (
    dbid oid,
    classid oid,
    objid oid,
    objsubid integer,
    refclassid oid,
    refobjid oid,
    deptype "char"
);

CREATE TABLE pg_catalog.pg_shdescription (
    objoid oid NOT NULL,
    classoid oid NOT NULL,
    description text COLLATE pg_catalog."C"
);

CREATE TABLE pg_catalog.pg_shseclabel (
    objoid oid NOT NULL,
    classoid oid NOT NULL,
    provider text NOT NULL COLLATE pg_catalog."C",
    label text COLLATE pg_catalog."C"
);

CREATE TABLE pg_catalog.pg_statistic (
    starelid oid NOT NULL,
    staattnum smallint NOT NULL,
    stainherit boolean NOT NULL,
    stanullfrac real,
    stawidth integer,
    stadistinct real,
    stakind1 smallint,
    stakind2 smallint,
    stakind3 smallint,
    stakind4 smallint,
    stakind5 smallint,
    staop1 oid,
    staop2 oid,
    staop3 oid,
    staop4 oid,
    staop5 oid,
    stacoll1 oid,
    stacoll2 oid,
    stacoll3 oid,
    stacoll4 oid,
    stacoll5 oid,
    stanumbers1 real[],
    stanumbers2 real[],
    stanumbers3 real[],
    stanumbers4 real[],
    stanumbers5 real[],
    stavalues1 anyarray,
    stavalues2 anyarray,
    stavalues3 anyarray,
    stavalues4 anyarray,
    stavalues5 anyarray
);

CREATE TABLE pg_catalog.pg_statistic_ext (
    oid oid NOT NULL,
    stxrelid oid,
    stxname name,
    stxnamespace oid,
    stxowner oid,
    stxkeys int2vector,
    stxstattarget smallint,
    stxkind "char"[],
    stxexprs pg_node_tree COLLATE pg_catalog."C"
);

CREATE TABLE pg_catalog.pg_statistic_ext_data (
    stxoid oid NOT NULL,
    stxdinherit boolean NOT NULL,
    stxdndistinct pg_ndistinct COLLATE pg_catalog."C",
    stxddependencies pg_dependencies COLLATE pg_catalog."C",
    stxdmcv pg_mcv_list COLLATE pg_catalog."C",
    stxdexpr pg_statistic[]
);

CREATE TABLE pg_catalog.pg_subscription (
    oid oid NOT NULL,
    subdbid oid,
    subskiplsn pg_lsn,
    subname name,
    subowner oid,
    subenabled boolean,
    subbinary boolean,
    substream "char",
    subtwophasestate "char",
    subdisableonerr boolean,
    subpasswordrequired boolean,
    subrunasowner boolean,
    subfailover boolean,
    subconninfo text COLLATE pg_catalog."C",
    subslotname name,
    subsynccommit text COLLATE pg_catalog."C",
    subpublications text[] COLLATE pg_catalog."C",
    suborigin text COLLATE pg_catalog."C"
);

CREATE TABLE pg_catalog.pg_subscription_rel (
    srsubid oid NOT NULL,
    srrelid oid NOT NULL,
    srsubstate "char",
    srsublsn pg_lsn
);

CREATE TABLE pg_catalog.pg_tablespace (
    oid oid NOT NULL,
    spcname name,
    spcowner oid,
    spcacl aclitem[],
    spcoptions text[] COLLATE pg_catalog."C"
);

CREATE TABLE pg_catalog.pg_transform (
    oid oid NOT NULL,
    trftype oid,
    trflang oid,
    trffromsql regproc,
    trftosql regproc
);

CREATE TABLE pg_catalog.pg_trigger (
    oid oid NOT NULL,
    tgrelid oid,
    tgparentid oid,
    tgname name,
    tgfoid oid,
    tgtype smallint,
    tgenabled "char",
    tgisinternal boolean,
    tgconstrrelid oid,
    tgconstrindid oid,
    tgconstraint oid,
    tgdeferrable boolean,
    tginitdeferred boolean,
    tgnargs smallint,
    tgattr int2vector,
    tgargs bytea,
    tgqual pg_node_tree COLLATE pg_catalog."C",
    tgoldtable name,
    tgnewtable name
);

CREATE TABLE pg_catalog.pg_ts_config (
    oid oid NOT NULL,
    cfgname name,
    cfgnamespace oid,
    cfgowner oid,
    cfgparser oid
);

CREATE TABLE pg_catalog.pg_ts_config_map (
    mapcfg oid NOT NULL,
    maptokentype integer NOT NULL,
    mapseqno integer NOT NULL,
    mapdict oid
);

CREATE TABLE pg_catalog.pg_ts_dict (
    oid oid NOT NULL,
    dictname name,
    dictnamespace oid,
    dictowner oid,
    dicttemplate oid,
    dictinitoption text COLLATE pg_catalog."C"
);

CREATE TABLE pg_catalog.pg_ts_parser (
    oid oid NOT NULL,
    prsname name,
    prsnamespace oid,
    prsstart regproc,
    prstoken regproc,
    prsend regproc,
    prsheadline regproc,
    prslextype regproc
);

CREATE TABLE pg_catalog.pg_ts_template (
    oid oid NOT NULL,
    tmplname name,
    tmplnamespace oid,
    tmplinit regproc,
    tmpllexize regproc
);

CREATE TABLE pg_catalog.pg_type (
    oid oid NOT NULL,
    typname name,
    typnamespace oid,
    typowner oid,
    typlen smallint,
    typbyval boolean,
    typtype "char",
    typcategory "char",
    typispreferred boolean,
    typisdefined boolean,
    typdelim "char",
    typrelid oid,
    typsubscript regproc,
    typelem oid,
    typarray oid,
    typinput regproc,
    typoutput regproc,
    typreceive regproc,
    typsend regproc,
    typmodin regproc,
    typmodout regproc,
    typanalyze regproc,
    typalign "char",
    typstorage "char",
    typnotnull boolean,
    typbasetype oid,
    typtypmod integer,
    typndims integer,
    typcollation oid,
    typdefaultbin pg_node_tree COLLATE pg_catalog."C",
    typdefault text COLLATE pg_catalog."C",
    typacl aclitem[]
);

CREATE TABLE pg_catalog.pg_user_mapping (
    oid oid NOT NULL,
    umuser oid,
    umserver oid,
    umoptions text[] COLLATE pg_catalog."C"
);

CREATE TABLE information_schema.sql_features (
    feature_id character varying COLLATE pg_catalog."C",
    feature_name character varying COLLATE pg_catalog."C",
    sub_feature_id character varying COLLATE pg_catalog."C",
    sub_feature_name character varying COLLATE pg_catalog."C",
    is_supported character varying(3) COLLATE pg_catalog."C",
    is_verified_by character varying COLLATE pg_catalog."C",
    comments character varying COLLATE pg_catalog."C"
);

CREATE TABLE information_schema.sql_implementation_info (
    implementation_info_id character varying COLLATE pg_catalog."C",
    implementation_info_name character varying COLLATE pg_catalog."C",
    integer_value integer,
    character_value character varying COLLATE pg_catalog."C",
    comments character varying COLLATE pg_catalog."C"
);

CREATE TABLE information_schema.sql_parts (
    feature_id character varying COLLATE pg_catalog."C",
    feature_name character varying COLLATE pg_catalog."C",
    is_supported character varying(3) COLLATE pg_catalog."C",
    is_verified_by character varying COLLATE pg_catalog."C",
    comments character varying COLLATE pg_catalog."C"
);

CREATE TABLE information_schema.sql_sizing (
    sizing_id integer,
    sizing_name character varying COLLATE pg_catalog."C",
    supported_value integer,
    comments character varying COLLATE pg_catalog."C"
);
