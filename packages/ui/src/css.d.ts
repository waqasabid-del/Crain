/** CSS Modules produce a class-name map at build time. */
declare module "*.module.css" {
  const classes: Readonly<Record<string, string>>;
  export default classes;
}
